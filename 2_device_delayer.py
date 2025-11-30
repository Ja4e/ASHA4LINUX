#!/usr/bin/env python3
import os
import sys
import subprocess
import threading
import time
import signal
import argparse
import re
import logging

# === CONFIG / ENVIRONMENT ===
logging.basicConfig(
	level=logging.INFO,
	format='[%(levelname)s] %(message)s'
)

DEFAULT_CONFIG = {
	'SINK1': 'sink_asha',
	'SINK2': 'sink_bt',
	'COMB': 'sink_combined',
	'DESC1': 'ASHA_Sink',
	'DESC2': 'BT_Sink',
	'DESC3': 'Combined_Sink',
	'TARGET1': os.environ.get('ASHA_SINK', 'asha_16450405641617933895'), 
	'TARGET2': os.environ.get('BT_SINK', 'bluez_output.*_*_*_*_*_*.1'), # dont forget to update this
	'LAT1': float(os.environ.get('ASHA_LAT', '34')), # highly dependant on the user's BT's latency with Qualcomm QCNCM865 on my current devices I have to set delay for ASHA to keep the audio combined for now I dont have a propbable way to control the left and right channels right now its only streaming all both to both.THe BT latency are NOT static unfortunately.
	'LAT2': float(os.environ.get('BT_LAT', '0'))
}

'''
WARNING!
DO NOT USE EASYEFFECT WITH THIS IT WILL BREAK


also it ONLY STREAMS TO DOUBLE CHANNEL BY DEFAULT using with left or right automatically will not work properly for BT devices
you can try use pwvucontrol software to control the channel
You can run this in background
'''

# === HELPERS ===
def run_cmd(cmd, capture=False, check=True):
	try:
		if capture:
			return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
		else:
			subprocess.check_call(cmd)
	except subprocess.CalledProcessError:
		if capture:
			return ""
		logging.warning(f"Command failed: {' '.join(cmd)}")
		return None

def extract_mac_from_sink(sink_name):
	match = re.search(r'bluez_output\.([0-9A-Fa-f_]+)\.\d+', sink_name)
	return match.group(1).replace('_', ':') if match else None

# === SINK CLASS ===
class Sink:
	def __init__(self, name, target, desc, channel='both', latency=0):
		self.name = name
		self.target = target
		self.desc = desc
		self.channel = channel
		# self.latency = int(latency)  # store as integer milliseconds
		self.latency = latency
		self.loopback_id = None
		self.module_id = None
		self.orig_volume = None

	def wait_for_sink(self):
		logging.info(f"Waiting for sink: {self.target}")
		out = run_cmd(['pactl', 'list', 'short', 'sinks'], capture=True)
		if out and any(line.split()[1] == self.target for line in out.splitlines()):
			logging.info(f"Sink already present: {self.target}")
			return
		sub = subprocess.Popen(['pactl', 'subscribe'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
		try:
			for line in sub.stdout:
				if "Event 'new' on sink" in line or "Event 'change' on sink" in line:
					out = run_cmd(['pactl', 'list', 'short', 'sinks'], capture=True)
					if out and any(line.split()[1] == self.target for line in out.splitlines()):
						logging.info(f"Sink detected: {self.target}")
						return
		finally:
			try:
				sub.kill()
			except Exception:
				pass

	def create_null_sink(self):
		self.module_id = run_cmd([
			'pactl', 'load-module', 'module-null-sink',
			f'sink_name={self.name}', f'sink_properties=device.description={self.desc}'
		], capture=True)
		return self.module_id

	def create_loopback(self):
		# Use self.latency value
		mapping = ''
		if self.channel == 'left':
			mapping = 'channel_map=front-left,front-left'
		elif self.channel == 'right':
			mapping = 'channel_map=front-right,front-right'

		cmd = [
			'pactl', 'load-module', 'module-loopback',
			f'source={self.name}.monitor',
			f'sink={self.target}',
			f'latency_msec={self.latency}',
			'volume=0x10000'
		]
		if mapping:
			cmd.append(mapping)
		
		# Clean up any existing loopback more thoroughly
		if self.loopback_id:
			for attempt in range(3):
				try:
					run_cmd(['pactl', 'unload-module', self.loopback_id], check=False)
					time.sleep(0.1)
					# Verify it's gone
					modules = run_cmd(['pactl', 'list', 'short', 'modules'], capture=True)
					if modules and str(self.loopback_id) in modules:
						logging.warning(f"Old module {self.loopback_id} still present, retrying...")
						time.sleep(0.2)
						continue
					break
				except Exception as e:
					logging.warning(f"Cleanup attempt {attempt + 1} failed: {e}")
					time.sleep(0.1)
			self.loopback_id = None
			time.sleep(0.15)
		
		# Create new loopback
		self.loopback_id = run_cmd(cmd, capture=True)
		if self.loopback_id:
			logging.info(f"Created loopback for {self.name} -> {self.target} (module {self.loopback_id}) with latency {self.latency} ms")
		else:
			logging.error(f"Failed to create loopback for {self.name}")
		return self.loopback_id

	def get_volume(self):
		out = run_cmd(['pactl', 'get-sink-volume', self.target], capture=True)
		if not out:
			self.orig_volume = '100%'
			return self.orig_volume
		for line in out.splitlines():
			if 'Volume:' in line:
				parts = line.split()
				# choose a robust extraction: last numeric percent in line
				for part in reversed(parts):
					if part.endswith('%'):
						self.orig_volume = part
						return self.orig_volume
		self.orig_volume = '100%'
		return self.orig_volume

	def set_volume(self, vol):
		if vol:
			run_cmd(['pactl', 'set-sink-volume', self.target, vol])

	def cleanup(self):
		if self.loopback_id:
			# Use thorough cleanup for loopback
			for attempt in range(3):
				try:
					run_cmd(['pactl', 'unload-module', self.loopback_id], check=False)
					time.sleep(0.1)
					modules = run_cmd(['pactl', 'list', 'short', 'modules'], capture=True)
					if modules and str(self.loopback_id) in modules:
						logging.warning(f"Module {self.loopback_id} still exists after cleanup, retrying...")
						time.sleep(0.2)
						continue
					break
				except Exception as e:
					logging.warning(f"Cleanup attempt {attempt + 1} for {self.loopback_id} failed: {e}")
					time.sleep(0.1)
			self.loopback_id = None
		if self.module_id:
			run_cmd(['pactl', 'unload-module', self.module_id], check=False)
			self.module_id = None
		# restore volume if we captured one earlier
		if self.orig_volume:
			try:
				self.set_volume(self.orig_volume)
			except Exception:
				logging.warning(f"Could not restore volume for {self.target}")

# === COMBINED SINK ===
class CombinedSink:
	def __init__(self, name, slaves, desc):
		self.name = name
		self.slaves = slaves
		self.desc = desc
		self.module_id = None

	def create(self, volume=None):
		self.module_id = run_cmd([
			'pactl', 'load-module', 'module-combine-sink',
			f'sink_name={self.name}',
			f'slaves={",".join(self.slaves)}',
			f'sink_properties=device.description={self.desc}'
		], capture=True)
		if self.module_id:
			run_cmd(['pactl', 'set-default-sink', self.name])
			if volume:
				# Set combined volume to match ASHA original volume
				run_cmd(['pactl', 'set-sink-volume', self.name, volume])
		return self.module_id

	def update_slaves(self, new_slaves):
		self.slaves = new_slaves
		run_cmd(['pactl', 'set-sink-slaves', self.name, ','.join(self.slaves)], check=False) # append , check=False if necessary

	def cleanup(self):
		if self.module_id:
			run_cmd(['pactl', 'unload-module', self.module_id], check=False)
			self.module_id = None

# === AUDIO MANAGER ===
class AudioManager:
	def __init__(self, config, args):
		self.args = args
		self.sink1 = Sink(config['SINK1'], config['TARGET1'], config['DESC1'], args.chan1, int(config['LAT1']))
		self.sink2 = Sink(config['SINK2'], config['TARGET2'], config['DESC2'], args.chan2, int(config['LAT2']))
		self.comb_sink = CombinedSink(config['COMB'], [self.sink1.name, self.sink2.name], config['DESC3'])
		self.stop_flag = threading.Event()
		signal.signal(signal.SIGINT, lambda s, f: self.stop_flag.set())
		signal.signal(signal.SIGTERM, lambda s, f: self.stop_flag.set())
		self.monitor_thread = None

	def cleanup_zombie_modules(self):
		"""Clean up any orphaned loopback modules that might exist"""
		modules = run_cmd(['pactl', 'list', 'short', 'modules'], capture=True)
		if not modules:
			return
		
		current_loopbacks = []
		if self.sink1.loopback_id:
			current_loopbacks.append(str(self.sink1.loopback_id))
		if self.sink2.loopback_id:
			current_loopbacks.append(str(self.sink2.loopback_id))
		
		for line in modules.splitlines():
			parts = line.split()
			if len(parts) >= 2 and 'module-loopback' in line:
				module_id = parts[0]
				# If this is a loopback module not in our current list, it might be a zombie
				if module_id not in current_loopbacks:
					# Check if it's using our sink names
					module_info = ' '.join(parts)
					if self.sink1.name in module_info or self.sink2.name in module_info:
						logging.warning(f"Cleaning up zombie loopback module: {module_id}")
						run_cmd(['pactl', 'unload-module', module_id], check=False)
						time.sleep(0.05)

	def try_reconnect_bt(self):
		mac = extract_mac_from_sink(self.sink2.target)
		if not mac:
			logging.warning("Could not extract MAC from BT sink name")
			return
		logging.info(f"Reconnecting BT: {mac}")
		for _ in range(3):
			try:
				subprocess.run(['bluetoothctl', 'connect', mac], check=True)
				logging.info("BT reconnect command sent")
				return
			except subprocess.CalledProcessError:
				time.sleep(1)
		logging.error("BT reconnect failed")

	def monitor_sinks(self):
		sub = subprocess.Popen(['pactl', 'subscribe'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
		try:
			for line in sub.stdout:
				if self.stop_flag.is_set(): break
				decoded = line.strip()
				if "Event 'remove' on sink" in decoded and self.sink1.target in decoded:
					logging.warning(f"ASHA removed: {self.sink1.target}")
					self.sink1.loopback_id = None
					self.sink1.wait_for_sink()
					self.sink1.create_loopback()
					self.comb_sink.update_slaves([self.sink1.name] + ([self.sink2.name] if self.sink2.loopback_id else []))
				elif "Event 'remove' on sink" in decoded and self.sink2.target in decoded:
					logging.warning(f"BT removed: {self.sink2.target}")
					if self.args.reconnect: self.try_reconnect_bt()
					if self.sink2.loopback_id:
						run_cmd(['pactl', 'unload-module', self.sink2.loopback_id], check=False)
						self.sink2.loopback_id = None
					self.comb_sink.update_slaves([self.sink1.name])
				elif "Event 'new' on sink" in decoded or "Event 'change' on sink" in decoded:
					out = run_cmd(['pactl', 'list', 'short', 'sinks'], capture=True)
					if not out:
						continue
					sink_names = [line.split()[1] for line in out.splitlines()]
					if self.sink2.target in sink_names and not self.sink2.loopback_id:
						self.sink2.create_loopback()
						self.comb_sink.update_slaves([self.sink1.name, self.sink2.name])
					if self.sink1.target in sink_names and not self.sink1.loopback_id:
						self.sink1.create_loopback()
						self.comb_sink.update_slaves([self.sink1.name] + ([self.sink2.name] if self.sink2.loopback_id else []))
		finally:
			try:
				sub.kill()
			except Exception:
				pass

	def cleanup(self):
		logging.info("Cleaning up...")
		# Clean up zombies first
		self.cleanup_zombie_modules()
		# unload combined sink first (so real sinks can be restored)
		self.comb_sink.cleanup()
		# restore individual sinks & volumes
		self.sink1.cleanup()
		self.sink2.cleanup()
		logging.info("Cleanup complete.")

	def set_latencies(self, lat1_ms: int, lat2_ms: int):
		"""
		Update stored latency values and, if a loopback exists, recreate it with the new latency.
		This function is safe to call at runtime.
		"""
		lat1_ms = int(lat1_ms)
		lat2_ms = int(lat2_ms)
		logging.info(f"Updating latencies: sink1={lat1_ms}ms sink2={lat2_ms}ms")
		
		# Clean up any zombies first
		self.cleanup_zombie_modules()
		
		# Update sink objects
		self.sink1.latency = lat1_ms
		self.sink2.latency = lat2_ms

		# Recreate loopbacks if they exist (unload -> wait -> create)
		for sink in (self.sink1, self.sink2):
			if sink.loopback_id:
				# Try multiple times to unload the module
				for attempt in range(3):
					try:
						run_cmd(['pactl', 'unload-module', sink.loopback_id], check=False)
						# Verify the module is actually gone
						time.sleep(0.1)
						modules = run_cmd(['pactl', 'list', 'short', 'modules'], capture=True)
						if modules and str(sink.loopback_id) in modules:
							logging.warning(f"Module {sink.loopback_id} still exists, retrying...")
							time.sleep(0.2)
							continue
						break
					except Exception as e:
						logging.warning(f"Attempt {attempt + 1} to unload module {sink.loopback_id} failed: {e}")
						time.sleep(0.1)
				
				sink.loopback_id = None
				# Give PulseAudio/pipewire more time to settle
				time.sleep(0.15)
				
				try:
					sink.create_loopback()
				except Exception as e:
					logging.error(f"Failed to recreate loopback for {sink.name}: {e}")

		# If combined sink exists, ensure slaves list still correct
		if self.comb_sink.module_id:
			slaves = [self.sink1.name] + ([self.sink2.name] if self.sink2.loopback_id else [])
			try:
				self.comb_sink.update_slaves(slaves)
			except Exception as e:
				logging.warning(f"Failed to update combined sink slaves: {e}")

	def run(self):
		# Save original default sink
		orig_default_sink = run_cmd(['pactl', 'get-default-sink'], capture=True)

		# Wait for sinks to appear
		self.sink1.wait_for_sink()
		self.sink2.wait_for_sink()

		# Save original volumes
		vol1 = self.sink1.get_volume()
		vol2 = self.sink2.get_volume()

		try:
			# Mute slave sinks first
			self.sink1.set_volume('0')
			self.sink2.set_volume('0')

			# Create null sinks
			self.sink1.create_null_sink()
			self.sink2.create_null_sink()

			# Create loopbacks
			self.sink1.create_loopback()
			self.sink2.create_loopback()

			
			# Create combined sink
			self.comb_sink.create(volume=vol1)

			run_cmd(['pactl', 'set-default-sink', self.comb_sink.name])
			
			# Force combined sink volume to ASHA original to handle active playback
			run_cmd(['pactl', 'set-sink-volume', self.comb_sink.name, vol1])

			# Set null sinks to 100% immediately
			self.sink1.set_volume('100%')
			self.sink2.set_volume('100%')

			logging.info(f"Combined sink ready with ASHA volume: {vol1}")

			# Start monitoring thread for sink disconnect/reconnect
			self.monitor_thread = threading.Thread(target=self.monitor_sinks, daemon=True)
			self.monitor_thread.start()

			while not self.stop_flag.is_set():
				time.sleep(1)

		finally:
			# FINAL CLEANUP (executes whether stop_flag set or exception)
			logging.info("Restoring original configuration...")

			# Unload combined sink first
			try:
				self.comb_sink.cleanup()
			except Exception:
				pass

			# Restore original volumes of real sinks
			try:
				self.sink1.set_volume(vol1)
			except Exception:
				pass
			try:
				self.sink2.set_volume(vol2)
			except Exception:
				pass

			# Restore original default sink
			if orig_default_sink:
				run_cmd(['pactl', 'set-default-sink', orig_default_sink])
				logging.info(f"Restored original default sink: {orig_default_sink}")

			# Cleanup individual sinks
			try:
				self.sink1.cleanup()
			except Exception:
				pass
			try:
				self.sink2.cleanup()
			except Exception:
				pass

			logging.info("Cleanup complete.")

# === ARGUMENT PARSING ===
parser = argparse.ArgumentParser(description='Combine ASHA and BT PulseAudio sinks')
parser.add_argument('chan1', nargs='?', default='both', choices=['left', 'right', 'both'])
parser.add_argument('chan2', nargs='?', default='both', choices=['left', 'right', 'both'])
parser.add_argument('-r', '--reconnect', action='store_true', help='Attempt to reconnect BT on disconnect')
parser.add_argument('--gtk', action='store_true', help='Open GTK UI to adjust latencies live')
parser.add_argument('--lat1', type=int, default=int(DEFAULT_CONFIG['LAT1']), help='Initial latency for sink1 (ms)')
parser.add_argument('--lat2', type=int, default=int(DEFAULT_CONFIG['LAT2']), help='Initial latency for sink2 (ms)')
args = parser.parse_args()

# Update DEFAULT_CONFIG latencies from CLI if provided
DEFAULT_CONFIG['LAT1'] = args.lat1
DEFAULT_CONFIG['LAT2'] = args.lat2

# === GTK UI ===
def run_gtk_ui(manager: AudioManager):
	# Import GTK only when needed to avoid hard dependency in non-ui mode
	try:
		import gi
		gi.require_version('Gtk', '3.0')
		from gi.repository import Gtk, GObject
	except Exception as e:
		logging.error("GTK UI requested but PyGObject not available or wrong version. Install python3-gi / python3-gobject (GTK3).")
		logging.debug(f"GTK import error: {e}")
		return

	class LatencyWindow(Gtk.Window):
		def __init__(self):
			super().__init__(title="Adjust Sink Latencies (ms)")
			# Gtk3 API: set_border_width exists
			self.set_border_width(12)
			self.set_default_size(320, 120)

			grid = Gtk.Grid(row_spacing=8, column_spacing=8, column_homogeneous=False)
			self.add(grid)

			# Labels and spin buttons
			label1 = Gtk.Label(label="Sink 1 (ASHA) latency (ms):", halign=Gtk.Align.START)
			label2 = Gtk.Label(label="Sink 2 (BT) latency (ms):", halign=Gtk.Align.START)

			adj1 = Gtk.Adjustment(value=manager.sink1.latency, lower=0, upper=2000, step_increment=1, page_increment=10)
			adj2 = Gtk.Adjustment(value=manager.sink2.latency, lower=0, upper=2000, step_increment=1, page_increment=10)
			self.spin1 = Gtk.SpinButton(adjustment=adj1, climb_rate=1, digits=0)
			self.spin2 = Gtk.SpinButton(adjustment=adj2, climb_rate=1, digits=0)

			apply_btn = Gtk.Button(label="Apply")
			apply_btn.connect("clicked", self.on_apply)

			reset_btn = Gtk.Button(label="Reset to defaults")
			reset_btn.connect("clicked", self.on_reset)

			close_btn = Gtk.Button(label="Close UI")
			# IMPORTANT: closing the UI should only quit the GTK main loop, NOT stop the manager.
			close_btn.connect("clicked", self.on_close)

			# Pack into grid
			grid.attach(label1, 0, 0, 1, 1)
			grid.attach(self.spin1, 1, 0, 1, 1)
			grid.attach(label2, 0, 1, 1, 1)
			grid.attach(self.spin2, 1, 1, 1, 1)

			button_box = Gtk.Box(spacing=8, orientation=Gtk.Orientation.HORIZONTAL)
			button_box.set_halign(Gtk.Align.END)
			button_box.pack_start(reset_btn, False, False, 0)
			button_box.pack_start(apply_btn, False, False, 0)
			button_box.pack_start(close_btn, False, False, 0)
			grid.attach(button_box, 0, 2, 2, 1)

			# Show initial values reflect manager
			self.spin1.set_value(manager.sink1.latency)
			self.spin2.set_value(manager.sink2.latency)

		def on_apply(self, button):
			new1 = int(self.spin1.get_value())
			new2 = int(self.spin2.get_value())
			# call manager to set latencies safely
			try:
				manager.set_latencies(new1, new2)
				self.show_info_dialog(f"Latencies updated: sink1={new1} ms, sink2={new2} ms")
			except Exception as e:
				self.show_info_dialog(f"Failed to update latencies: {e}")

		def on_reset(self, button):
			self.spin1.set_value(int(DEFAULT_CONFIG['LAT1']))
			self.spin2.set_value(int(DEFAULT_CONFIG['LAT2']))
			self.on_apply(button)

		def on_close(self, button):
			# Only quit GTK main loop, do NOT set manager.stop_flag here.
			# Manager continues to run until user sends SIGINT (Ctrl-C).
			self.destroy()
			Gtk.main_quit()

		def show_info_dialog(self, message):
			d = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.INFO,
				buttons=Gtk.ButtonsType.OK, text=message)
			d.run()
			d.destroy()

	# Create and show window
	win = LatencyWindow()
	# Do NOT set a route that triggers manager.stop_flag on destroy.
	win.connect("destroy", lambda w: Gtk.main_quit())
	win.show_all()
	# This blocks the main thread until UI closed; after that, control returns to caller
	Gtk.main()

# === ENTRY POINT ===
if __name__ == '__main__':
	manager = AudioManager(DEFAULT_CONFIG, args)

	# If GTK UI requested, run manager in a background thread and run GTK in main thread
	if args.gtk:
		# Start manager.run in a daemon thread
		manager_thread = threading.Thread(target=manager.run, daemon=True)
		manager_thread.start()

		# Give manager a short moment to initialize
		time.sleep(0.1)

		# Run GTK UI (this call blocks until UI closed). IMPORTANT: closing UI will NOT stop the manager.
		try:
			run_gtk_ui(manager)
		except KeyboardInterrupt:
			# if user pressed Ctrl-C while GTK running
			pass

		# After the GTK UI closes, keep the manager running until the user Ctrl-C the whole process.
		# This reproduces the original behavior: UI is only a control surface, manager runs until explicit exit.
		try:
			while manager_thread.is_alive():
				time.sleep(0.2)
		except KeyboardInterrupt:
			# user requested exit — signal manager to stop and wait for cleanup
			manager.stop_flag.set()
			# wait a short while for thread to clean up
			manager_thread.join(timeout=5)
	else:
		# Normal non-GTK mode: run manager in current thread (blocks until exit)
		try:
			manager.run()
		except KeyboardInterrupt:
			manager.stop_flag.set()
			# give run() finalizer a chance to run
			time.sleep(0.1)
