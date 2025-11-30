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
	'TARGET2': os.environ.get('BT_SINK', 'bluez_output.*_*_*_*_*_*.1'),  # dont forget to update this
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

# ----------------- Sink classes ----------------- #
class Sink:
	def __init__(self, name, target, desc, channel='both', latency=0):
		self.name = name
		self.target = target
		self.desc = desc
		self.channel = channel
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
			try: sub.kill()
			except Exception: pass

	def create_null_sink(self):
		self.module_id = run_cmd([
			'pactl', 'load-module', 'module-null-sink',
			f'sink_name={self.name}', f'sink_properties=device.description={self.desc}'
		], capture=True)
		return self.module_id

	def create_loopback(self):
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

		if self.loopback_id:
			self.cleanup_loopback()
		
		self.loopback_id = run_cmd(cmd, capture=True)
		if self.loopback_id:
			logging.info(f"Created loopback for {self.name} -> {self.target} (module {self.loopback_id}) with latency {self.latency} ms")
		else:
			logging.error(f"Failed to create loopback for {self.name}")
		return self.loopback_id

	def cleanup_loopback(self):
		for attempt in range(3):
			try:
				run_cmd(['pactl', 'unload-module', self.loopback_id], check=False)
				time.sleep(0.1)
				modules = run_cmd(['pactl', 'list', 'short', 'modules'], capture=True)
				if modules and str(self.loopback_id) in modules:
					logging.warning(f"Loopback {self.loopback_id} still present, retrying...")
					time.sleep(0.2)
					continue
				break
			except Exception as e:
				logging.warning(f"Cleanup attempt {attempt + 1} failed: {e}")
				time.sleep(0.1)
		self.loopback_id = None
		time.sleep(0.1)

	def get_volume(self):
		out = run_cmd(['pactl', 'get-sink-volume', self.target], capture=True)
		if not out:
			self.orig_volume = '100%'
			return self.orig_volume
		for line in out.splitlines():
			if 'Volume:' in line:
				for part in reversed(line.split()):
					if part.endswith('%'):
						self.orig_volume = part
						return self.orig_volume
		self.orig_volume = '100%'
		return self.orig_volume

	def set_volume(self, vol):
		if vol:
			run_cmd(['pactl', 'set-sink-volume', self.target, vol])

	def cleanup(self):
		self.cleanup_loopback()
		if self.module_id:
			run_cmd(['pactl', 'unload-module', self.module_id], check=False)
			self.module_id = None
		if self.orig_volume:
			try:
				self.set_volume(self.orig_volume)
			except Exception:
				logging.warning(f"Could not restore volume for {self.target}")

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
				run_cmd(['pactl', 'set-sink-volume', self.name, volume])
		return self.module_id

	def update_slaves(self, new_slaves):
		self.slaves = new_slaves
		run_cmd(['pactl', 'set-sink-slaves', self.name, ','.join(self.slaves)], check=False)

	def cleanup(self):
		if self.module_id:
			run_cmd(['pactl', 'unload-module', self.module_id], check=False)
			self.module_id = None

# ================= AUDIO MANAGER =================
class AudioManager:
	def __init__(self, config, args):
		self.args = args
		self.sink1 = Sink(config['SINK1'], config['TARGET1'], config['DESC1'], args.chan1, int(config['LAT1']))
		self.sink2 = Sink(config['SINK2'], config['TARGET2'], config['DESC2'], args.chan2, int(config['LAT2']))
		self.comb_sink = CombinedSink(config['COMB'], [self.sink1.name, self.sink2.name], config['DESC3'])
		self.stop_flag = threading.Event()
		self.monitor_thread = None
		self.setup_signal_handlers()

	def setup_signal_handlers(self):
		import gi
		gi.require_version('Gtk', '3.0')
		from gi.repository import GLib, Gtk

		def sig_handler(signum, frame):
			logging.info(f"Signal {signum} received, stopping...")
			self.stop_flag.set()
			GLib.idle_add(Gtk.main_quit)

		signal.signal(signal.SIGINT, sig_handler)
		signal.signal(signal.SIGTERM, sig_handler)

	def cleanup_zombie_modules(self):
		modules = run_cmd(['pactl', 'list', 'short', 'modules'], capture=True)
		if not modules: return
		current_loopbacks = [str(l) for l in [self.sink1.loopback_id, self.sink2.loopback_id] if l]
		for line in modules.splitlines():
			if 'module-loopback' in line:
				module_id = line.split()[0]
				if module_id not in current_loopbacks and (self.sink1.name in line or self.sink2.name in line):
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
			while not self.stop_flag.is_set():
				line = sub.stdout.readline()
				if not line: continue
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
					if not out: continue
					sink_names = [l.split()[1] for l in out.splitlines()]
					if self.sink2.target in sink_names and not self.sink2.loopback_id:
						self.sink2.create_loopback()
						self.comb_sink.update_slaves([self.sink1.name, self.sink2.name])
					if self.sink1.target in sink_names and not self.sink1.loopback_id:
						self.sink1.create_loopback()
						self.comb_sink.update_slaves([self.sink1.name] + ([self.sink2.name] if self.sink2.loopback_id else []))
		finally:
			try: sub.kill()
			except Exception: pass

	def cleanup(self):
		logging.info("Cleaning up AudioManager...")
		self.cleanup_zombie_modules()
		self.comb_sink.cleanup()
		self.sink1.cleanup()
		self.sink2.cleanup()
		logging.info("Cleanup complete.")

	def set_latencies(self, lat1_ms: int, lat2_ms: int):
		lat1_ms = int(lat1_ms)
		lat2_ms = int(lat2_ms)
		logging.info(f"Updating latencies: sink1={lat1_ms}ms sink2={lat2_ms}ms")
		self.cleanup_zombie_modules()
		self.sink1.latency = lat1_ms
		self.sink2.latency = lat2_ms
		for sink in (self.sink1, self.sink2):
			if sink.loopback_id:
				sink.cleanup_loopback()
				sink.create_loopback()
		if self.comb_sink.module_id:
			slaves = [self.sink1.name] + ([self.sink2.name] if self.sink2.loopback_id else [])
			self.comb_sink.update_slaves(slaves)

	def run(self):
		orig_default_sink = run_cmd(['pactl', 'get-default-sink'], capture=True)
		self.sink1.wait_for_sink()
		self.sink2.wait_for_sink()
		vol1 = self.sink1.get_volume()
		vol2 = self.sink2.get_volume()

		try:
			self.sink1.set_volume('0')
			self.sink2.set_volume('0')
			self.sink1.create_null_sink()
			self.sink2.create_null_sink()
			self.sink1.create_loopback()
			self.sink2.create_loopback()
			self.comb_sink.create(volume=vol1)
			run_cmd(['pactl', 'set-default-sink', self.comb_sink.name])
			self.sink1.set_volume('100%')
			self.sink2.set_volume('100%')
			logging.info(f"Combined sink ready with ASHA volume: {vol1}")

			self.monitor_thread = threading.Thread(target=self.monitor_sinks, daemon=True)
			self.monitor_thread.start()

			while not self.stop_flag.is_set():
				time.sleep(0.5)

		finally:
			logging.info("Restoring original configuration...")
			self.cleanup()
			if orig_default_sink:
				run_cmd(['pactl', 'set-default-sink', orig_default_sink])
				logging.info(f"Restored original default sink: {orig_default_sink}")

# ================= ARG PARSING =================
parser = argparse.ArgumentParser(description='Combine ASHA and BT PulseAudio sinks')
parser.add_argument('chan1', nargs='?', default='both', choices=['left', 'right', 'both'])
parser.add_argument('chan2', nargs='?', default='both', choices=['left', 'right', 'both'])
parser.add_argument('-r', '--reconnect', action='store_true', help='Attempt to reconnect BT on disconnect')
parser.add_argument('--gtk', action='store_true', help='Open GTK UI to adjust latencies live')
parser.add_argument('--lat1', type=int, default=int(DEFAULT_CONFIG['LAT1']), help='Initial latency for sink1 (ms)')
parser.add_argument('--lat2', type=int, default=int(DEFAULT_CONFIG['LAT2']), help='Initial latency for sink2 (ms)')
args = parser.parse_args()
DEFAULT_CONFIG['LAT1'] = args.lat1
DEFAULT_CONFIG['LAT2'] = args.lat2

# ================= GTK UI =================
gtk_window = None
def run_gtk_ui(manager: AudioManager):
	import gi
	gi.require_version('Gtk', '3.0')
	from gi.repository import Gtk, GLib

	class LatencyWindow(Gtk.Window):
		def __init__(self):
			super().__init__(title="Adjust Sink Latencies (ms)")
			self.set_border_width(12)
			self.set_default_size(320, 120)
			grid = Gtk.Grid(row_spacing=8, column_spacing=8)
			self.add(grid)

			label1 = Gtk.Label(label="Sink 1 (ASHA) latency (ms):", halign=Gtk.Align.START)
			label2 = Gtk.Label(label="Sink 2 (BT) latency (ms):", halign=Gtk.Align.START)
			adj1 = Gtk.Adjustment(value=manager.sink1.latency, lower=0, upper=2000, step_increment=1)
			adj2 = Gtk.Adjustment(value=manager.sink2.latency, lower=0, upper=2000, step_increment=1)
			self.spin1 = Gtk.SpinButton(adjustment=adj1, climb_rate=1, digits=0)
			self.spin2 = Gtk.SpinButton(adjustment=adj2, climb_rate=1, digits=0)

			apply_btn = Gtk.Button(label="Apply")
			apply_btn.connect("clicked", self.on_apply)
			reset_btn = Gtk.Button(label="Reset to defaults")
			reset_btn.connect("clicked", self.on_reset)
			close_btn = Gtk.Button(label="Close UI")
			close_btn.connect("clicked", self.on_close)

			grid.attach(label1, 0, 0, 1, 1)
			grid.attach(self.spin1, 1, 0, 1, 1)
			grid.attach(label2, 0, 1, 1, 1)
			grid.attach(self.spin2, 1, 1, 1, 1)
			button_box = Gtk.Box(spacing=8, orientation=Gtk.Orientation.HORIZONTAL)
			button_box.pack_start(reset_btn, False, False, 0)
			button_box.pack_start(apply_btn, False, False, 0)
			button_box.pack_start(close_btn, False, False, 0)
			grid.attach(button_box, 0, 2, 2, 1)

			self.spin1.set_value(manager.sink1.latency)
			self.spin2.set_value(manager.sink2.latency)

		def on_apply(self, button):
			try:
				manager.set_latencies(int(self.spin1.get_value()), int(self.spin2.get_value()))
			except Exception as e:
				logging.error(f"Failed to apply latencies: {e}")

		def on_reset(self, button):
			self.spin1.set_value(int(DEFAULT_CONFIG['LAT1']))
			self.spin2.set_value(int(DEFAULT_CONFIG['LAT2']))
			self.on_apply(button)

		def on_close(self, button):
			manager.stop_flag.set()
			self.destroy()
			Gtk.main_quit()

	global gtk_window
	gtk_window = LatencyWindow()
	gtk_window.connect("destroy", lambda w: Gtk.main_quit())
	gtk_window.show_all()
	Gtk.main()

def close_gtk_ui():
	global gtk_window
	if gtk_window:
		import gi
		gi.require_version('Gtk', '3.0')
		from gi.repository import Gtk, GLib

		def _destroy():
			global gtk_window
			if gtk_window:
				try: gtk_window.destroy()
				except Exception: pass
				gtk_window = None
				Gtk.main_quit()
			return False

		GLib.idle_add(_destroy)

# ================= MAIN =================
if __name__ == '__main__':
	manager = AudioManager(DEFAULT_CONFIG, args)
	try:
		if args.gtk:
			manager_thread = threading.Thread(target=manager.run)
			manager_thread.start()
			time.sleep(0.1)
			try:
				run_gtk_ui(manager)
			except KeyboardInterrupt:
				close_gtk_ui()
				manager.stop_flag.set()
				manager_thread.join()
				sys.exit(0)
			while manager_thread.is_alive():
				time.sleep(0.2)
		else:
			manager.run()
	except KeyboardInterrupt:
		manager.stop_flag.set()
		close_gtk_ui()
		sys.exit(0)
