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
		self.latency = latency
		self.loopback_id = None
		self.module_id = None
		self.orig_volume = None

	def wait_for_sink(self):
		logging.info(f"Waiting for sink: {self.target}")
		out = run_cmd(['pactl', 'list', 'short', 'sinks'], capture=True)
		if any(line.split()[1] == self.target for line in out.splitlines()):
			logging.info(f"Sink already present: {self.target}")
			return
		sub = subprocess.Popen(['pactl', 'subscribe'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
		try:
			for line in sub.stdout:
				if "Event 'new' on sink" in line or "Event 'change' on sink" in line:
					out = run_cmd(['pactl', 'list', 'short', 'sinks'], capture=True)
					if any(line.split()[1] == self.target for line in out.splitlines()):
						logging.info(f"Sink detected: {self.target}")
						return
		finally:
			sub.kill()

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
		self.loopback_id = run_cmd(cmd, capture=True)
		return self.loopback_id

	def get_volume(self):
		out = run_cmd(['pactl', 'get-sink-volume', self.target], capture=True)
		for line in out.splitlines():
			if 'Volume:' in line:
				parts = line.split()
				if len(parts) >= 5:
					self.orig_volume = parts[4]
					return self.orig_volume
		self.orig_volume = '100%'
		return self.orig_volume

	def set_volume(self, vol):
		if vol:
			run_cmd(['pactl', 'set-sink-volume', self.target, vol])

	def cleanup(self):
		if self.loopback_id:
			run_cmd(['pactl', 'unload-module', self.loopback_id], check=False)
		if self.module_id:
			run_cmd(['pactl', 'unload-module', self.module_id], check=False)
		if self.orig_volume:
			try:
				self.set_volume(self.orig_volume)
			except:
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
		run_cmd(['pactl', 'set-default-sink', self.name])
		if volume:
			# Set combined volume to match ASHA original volume
			run_cmd(['pactl', 'set-sink-volume', self.name, volume])
		return self.module_id

	def update_slaves(self, new_slaves):
		self.slaves = new_slaves
		run_cmd(['pactl', 'set-sink-slaves', self.name, ','.join(self.slaves)])

	def cleanup(self):
		if self.module_id:
			run_cmd(['pactl', 'unload-module', self.module_id], check=False)

# === AUDIO MANAGER ===
class AudioManager:
	def __init__(self, config, args):
		self.args = args
		self.sink1 = Sink(config['SINK1'], config['TARGET1'], config['DESC1'], args.chan1, config['LAT1'])
		self.sink2 = Sink(config['SINK2'], config['TARGET2'], config['DESC2'], args.chan2, config['LAT2'])
		self.comb_sink = CombinedSink(config['COMB'], [self.sink1.name, self.sink2.name], config['DESC3'])
		self.stop_flag = threading.Event()
		signal.signal(signal.SIGINT, lambda s, f: self.stop_flag.set())
		signal.signal(signal.SIGTERM, lambda s, f: self.stop_flag.set())

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
					sink_names = [line.split()[1] for line in out.splitlines()]
					if self.sink2.target in sink_names and not self.sink2.loopback_id:
						self.sink2.create_loopback()
						self.comb_sink.update_slaves([self.sink1.name, self.sink2.name])
					if self.sink1.target in sink_names and not self.sink1.loopback_id:
						self.sink1.create_loopback()
						self.comb_sink.update_slaves([self.sink1.name] + ([self.sink2.name] if self.sink2.loopback_id else []))
		finally:
			sub.kill()

	def cleanup(self):
		logging.info("Cleaning up...")
		self.comb_sink.cleanup()
		self.sink1.cleanup()
		self.sink2.cleanup()
		logging.info("Cleanup complete.")

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
			monitor_thread = threading.Thread(target=self.monitor_sinks, daemon=True)
			monitor_thread.start()

			while not self.stop_flag.is_set():
				time.sleep(1)

		finally:
			logging.info("Restoring original configuration...")

			# Unload combined sink first
			self.comb_sink.cleanup()

			# Restore original volumes of real sinks
			self.sink1.set_volume(vol1)
			self.sink2.set_volume(vol2)

			# Restore original default sink
			if orig_default_sink:
				run_cmd(['pactl', 'set-default-sink', orig_default_sink])
				logging.info(f"Restored original default sink: {orig_default_sink}")

			# Cleanup individual sinks
			self.sink1.cleanup()
			self.sink2.cleanup()

			logging.info("Cleanup complete.")


# === ARGUMENT PARSING ===
parser = argparse.ArgumentParser(description='Combine ASHA and BT PulseAudio sinks')
parser.add_argument('chan1', nargs='?', default='both', choices=['left', 'right', 'both'])
parser.add_argument('chan2', nargs='?', default='both', choices=['left', 'right', 'both'])
parser.add_argument('-r', '--reconnect', action='store_true', help='Attempt to reconnect BT on disconnect')
args = parser.parse_args()

# === ENTRY POINT ===
if __name__ == '__main__':
	manager = AudioManager(DEFAULT_CONFIG, args)
	manager.run()
