#!/usr/bin/env python3
"""
This is a very sophisticated script that should improve the chances of a successful connection
reduces the chances of getting reported org.bluez.Error.Failed connection abort-by-local issues.
Tested with Intel AX210 – it should also work with other functional Bluetooth adapters.
It is now comparable to Apple's Bluetooth approach to ASHA devices.


This script minimizes **unintended disconnections** with ASHA G.722 hearing aids
by handling edge cases and reduces real-world timing unpredictability that 
normally affect connection success. Without it, stable connections often rely 
on physical-layer 'luck' and system-specific timing.

If the audio is choppy, delayed, or sounds like it is shifting from ear to ear, then your adapter may not be able to keep up with the bandwidth requirements.
Try connecting a single device and see if the quality improves or restart this script it usually fixes for me.


PLEASE DO GO https://github.com/thewierdnut/asha_pipewire_sink.git documentations BEFORE USE

Required by SIG documentations:

/etc/modprobe.d/bluetooth_asha.conf
options bluetooth enable_ecred=1

/etc/bluetooth/main.conf
PLease do make sure you include these into that main.conf
These configuration items will already already be present, but they are commented out, and have the wrong values. Note that these values are set in units of 1.25ms, so 20 / 1.25 = 16

[LE]
# LE default connection parameters.  These values are superceeded by any
# specific values provided via the Load Connection Parameters interface
MinConnectionInterval=16
MaxConnectionInterval=16
ConnectionLatency=10
ConnectionSupervisionTimeout=100

I find setting from ConnectionSupervisionTimeout=100 to 2000 to be better in connections

My personal config:
DiscoverableTimeout = 0
ControllerMode = le #This might not even be necessary just igore this if you actually wanted to use this
FastConnectable = true

KernelExperimental = true
ReconnectIntervals=1,1,2,3,5,8,13,21,34,55 # under policy section

these may not suitable for all so just ignore them

dont turn on if you have this particular MEDEL product:
Experimental = true


For people who has MEDEL's latest products it inbuilt low energy capabilities but not for audio streaming but rather for controlling and "find-my" app functionalities, and the audio stream adapter is for ble audio streaming capabilities
but currently it does not work properly buecase My laptop has not managed to find them thus renders these passive advertising useless however I find pairing between two are more solid with it so its may or may not worthed it
the latest updated program by a guy does proper active advertising connection between devices requires proper setup that requires you to uncomment in that /etc/bluetooth/main.conf command to Experimental = true
but this isnt the case it causes problems which will report undocumented error: DBus.Error:org.bluez.Error.Failed: Operation failed with ATT error: 0x48 
So for people who owns this device please do not enable this it will leads to problematic in reconnections.

Enable 2M PHY (optional):
Each devices may present different result during the handshake connection will implement a feature to execute them on the go making it more configurable through json

# Check the existing phys
sudo btmgmt phy
Supported phys: BR1M1SLOT BR1M3SLOT BR1M5SLOT EDR2M1SLOT EDR2M3SLOT EDR2M5SLOT EDR3M1SLOT EDR3M3SLOT EDR3M5SLOT LE1MTX LE1MRX LE2MTX LE2MRX LECODEDTX LECODEDRX
Configurable phys: BR1M3SLOT BR1M5SLOT EDR2M1SLOT EDR2M3SLOT EDR2M5SLOT EDR3M1SLOT EDR3M3SLOT EDR3M5SLOT LE2MTX LE2MRX LECODEDTX LECODEDRX
Selected phys: BR1M1SLOT BR1M3SLOT BR1M5SLOT EDR2M1SLOT EDR2M3SLOT EDR2M5SLOT EDR3M1SLOT EDR3M3SLOT EDR3M5SLOT LE1MTX LE1MRX

# copy the Selected phys, and add the new LE2MTX LE2MRX values to it
sudo btmgmt phy BR1M1SLOT BR1M3SLOT BR1M5SLOT EDR2M1SLOT EDR2M3SLOT EDR2M5SLOT EDR3M1SLOT EDR3M3SLOT EDR3M5SLOT LE1MTX LE1MRX LE2MTX LE2MRX


#The latest three commits from that asha is currently very broken (Fixed)
#try attempt running git reset --hard HEAD~1 in that commit before compiling 

Setcap is implemented for 1/2 phy protocols for convience 
I chose 1mphy because of it's reliabilities during the streaming
you could set when to use or not

If it's connected sucessfully please do not unpair them because you got the security key to get connect them back, only unpair when your devices refused to connect them back multiple times and then try to attempt to repair them back. Usually for MEDEL's audiostream adapter requires the AudioKey 2 app on your mobile phone in the audiostream section to "update" them connect them back will give you higher chances to get it paired sucessfully usually sucess in one shot, one time, it somehow more reliable than having it your devices restarted multiple times to attempt it connect back.

Usually, if connection return try to restart this device and try to rerun the script. 


"""

"""
This script aims to assist all annonying G.722 bluetooth connection issues 
"""

# ==============
#  DEPENDENCIES
# ==============
import os
import pty
import subprocess
import time
import sys
import signal
import threading
import select
import argparse
import re
import asyncio
import random
import logging
from typing import List, Tuple, Optional, Set, Dict, Any
from colorama import init as colorama_init, Fore, Style
import dbus
import dbus.exceptions
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import fcntl
import termios
import json
import psutil
import queue

colorama_init(autoreset=True)

# ------------------------------
# GLOBAL LOCK FOR THREAD SAFETY
# ------------------------------
global_lock = threading.RLock()

# ------------------------------
# Logging Setup
# ------------------------------
DEBUG: bool = os.getenv('DEBUG', '0') == '1'
LOG_FORMAT = f"%(asctime)s {Fore.CYAN}[DEBUG] %(message)s{Style.RESET_ALL}" if DEBUG else "%(asctime)s [INFO] %(message)s"
logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO,
					format=LOG_FORMAT,
					datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# ------------------------------
# LOGGING UTILITIES
# ------------------------------
def log_info(message: str, color: str = Fore.GREEN) -> None:
	"""Consistent info logging with optional color"""
	logger.info(f"{color}{message}{Style.RESET_ALL}")

def log_warning(message: str) -> None:
	"""Consistent warning logging"""
	logger.warning(f"{Fore.YELLOW}{message}{Style.RESET_ALL}")

def log_error(message: str) -> None:
	"""Consistent error logging"""
	logger.error(f"{Fore.RED}{message}{Style.RESET_ALL}")

def log_debug(message: str) -> None:
	"""Consistent debug logging"""
	if DEBUG:
		logger.debug(f"{Fore.CYAN}{message}{Style.RESET_ALL}")

def log_config(message: str) -> None:
	"""Consistent config logging"""
	logger.info(f"{Fore.MAGENTA}[config] {message}{Style.RESET_ALL}")

def log_asha(message: str) -> None:
	"""Consistent ASHA logging"""
	logger.info(f"{Fore.BLUE}[ASHA] {message}{Style.RESET_ALL}")

def log_device(message: str, device_type: str = "device") -> None:
	"""Consistent device logging with type-based coloring"""
	colors = {
		"primary": Fore.GREEN,
		"secondary": Fore.YELLOW,
		"device": Fore.BLUE
	}
	color = colors.get(device_type, Fore.BLUE)
	logger.info(f"{color}[{device_type.upper()}] {message}{Style.RESET_ALL}")

def log_connection(message: str, status: str = "info") -> None:
	"""Consistent connection status logging"""
	colors = {
		"success": Fore.GREEN,
		"error": Fore.RED,
		"warning": Fore.YELLOW,
		"info": Fore.BLUE
	}
	color = colors.get(status, Fore.BLUE)
	logger.info(f"{color}[CONN] {message}{Style.RESET_ALL}")

def log_gatt(message: str) -> None:
	"""Consistent GATT operation logging"""
	logger.info(f"{Fore.CYAN}[GATT] {message}{Style.RESET_ALL}")

def log_reconnection(message: str) -> None:
	"""Consistent reconnection logging"""
	logger.info(f"{Fore.MAGENTA}[RECONN] {message}{Style.RESET_ALL}")

def log_delay(message: str) -> None:
	"""Consistent delay logging"""
	logger.info(f"{Fore.CYAN}[DELAY] {message}{Style.RESET_ALL}")

def log_audio(message: str) -> None:
	"""Consistent audio sink logging"""
	logger.info(f"{Fore.MAGENTA}[AUDIO] {message}{Style.RESET_ALL}")

def log_gtk(message: str) -> None:
	"""Consistent GTK UI logging"""
	logger.info(f"{Fore.CYAN}[GTK] {message}{Style.RESET_ALL}")

# ------------------------------
# CONFIGURATION
# ------------------------------
config_path = "~/.config/asha_manager/config.json"

def load_config(config_path: str) -> dict:
	"""
	Load configuration from JSON file, merging defaults with user overrides.
	"""
	def get_default_config() -> dict:
		return {
			"Devices": {
				"Primary": [""],
				"Secondary": [""],
			},
			"global": {
				"Separate_boolean": True,
				"Filter_DFU": True,
				"Max_Devices": 2,
				"Priority_Primary": True,
			},
			"GATT": {
				"Allow": True,
				"Volume": {
					"ID": "00e4ca9e-ab14-41e4-8823-f9e70c7e91df",
					"Value": "0xff",
				},
				"Volume_Sec": {
					"ID": "00e4ca9e-ab14-41e4-8823-f9e70c7e91df", 
					"Value": "0xff",
				},
				"Trigger": {
					"Boolean": True,
					"Modes": "increment",
					"Duration_s": 0.3,
				},
				"Frequency_int": 1,
				"Detect_loss": False,
				"Per_Device_Volume": True
			},
			"DELAY": {
				"RETRY": "R",
				"DEFAULT_RETRY": 0.0,
				"MAX_TIMEOUT": "R",
				"Timeout_qs": "R",
			},
			"Reconnection": {
				"Secondary": {
					"Enabled": True,
					"Mode": "incremental",
					"Initial_Delay": 5.0,
					"Max_Delay": 60.0,
					"Max_Attempts": 10,
					"Backoff_Multiplier": 1.5
				}
			},
			"Connection_Delay": {
				"Enabled": False,
				"Delay_Seconds": 5.0,
				"Only_After_Both": True,
				"Apply_To": "all",  # "all", "primary", "secondary"
				"Reset_After_Disconnect": True
			},
			"AudioCombiner": {
				"Enabled": True,
				"GTK_UI": False,
				"SINK1": "sink_asha",
				"SINK2": "sink_bt",
				"COMB": "sink_combined",
				"DESC1": "ASHA_Sink",
				"DESC2": "BT_Sink",
				"DESC3": "Combined_Sink",
				"TARGET1": os.environ.get('ASHA_SINK', 'asha_16450405641617933895'),  # dont forget to update this
				"TARGET2": os.environ.get('BT_SINK', 'bluez_output.XX_XX_XX_XX_XX_XX.1'), # dont forget to update this Do use  "pactl list short sinks" to find the proper sink name (its persistent)
				"LAT1": int(os.environ.get('ASHA_LAT', '34')), # highly dependant on the user's BT's latency with Qualcomm QCNCM865 on my current devices I have to set delay for ASHA to keep the audio combined for now I dont have a propbable way to control the left and right channels right now its only streaming all both to both.THe BT latency are NOT static unfortunately.
				"LAT2": int(os.environ.get('BT_LAT', '0')),
				"CHAN1": "both",  # "left", "right", "both"
				"CHAN2": "both",  # "left", "right", "both"
				"Auto_Adjust": True,
				"Monitor_Interval": 1.0
			},
			"Blacklist": [
				"AudioStream Adapter DFU",
			]
		}

	def deep_merge(default: dict, override: dict) -> None:
		for key, value in override.items():
			if key in default and isinstance(default[key], dict) and isinstance(value, dict):
				deep_merge(default[key], value)
			else:
				default[key] = value

	def migrate_old_config(config: dict) -> dict:
		devices = config.get("Devices", {})
		if "Primary" in devices and isinstance(devices["Primary"], dict):
			primary_name = devices["Primary"].get("Name", "")
			if primary_name and isinstance(primary_name, str):
				config["Devices"]["Primary"] = [primary_name] if primary_name else []
		if "Secondary" in devices and isinstance(devices["Secondary"], dict):
			secondary_name = devices["Secondary"].get("Name", "")
			if secondary_name and isinstance(secondary_name, str):
				config["Devices"]["Secondary"] = [secondary_name] if secondary_name else []
		return config

	default_config = get_default_config()
	os.makedirs(os.path.dirname(config_path), exist_ok=True)

	if os.path.isfile(config_path):
		try:
			with open(config_path, 'r') as f:
				user_config = json.load(f)
			user_config = migrate_old_config(user_config)
			deep_merge(default_config, user_config)
			log_config(f"Loaded configuration from: {config_path}")
		except (json.JSONDecodeError, IOError) as e:
			log_warning(f"Failed to load config, using defaults: {e}")
	else:
		try:
			with open(config_path, 'w') as f:
				json.dump(default_config, f, indent=4)
			log_config(f"Created default config at: {config_path}")
		except IOError as e:
			log_error(f"Failed to write default config: {e}")

	return default_config

def save_config():
	"""Save the current configuration to file"""
	with global_lock:
		try:
			with open(CONFIG_PATH, 'w') as f:
				json.dump(config, f, indent=4)
			log_config("Configuration saved to file")
		except Exception as e:
			log_error(f"Failed to save config: {e}")

# Path to configuration file
CONFIG_PATH = os.path.expanduser(config_path)
config = load_config(CONFIG_PATH)

# Extract device lists from config
PRIMARY_DEVICES: List[str] = config["Devices"].get("Primary", [])
SECONDARY_DEVICES: List[str] = config["Devices"].get("Secondary", [])
MAX_DEVICES: int = config["global"].get("Max_Devices", 2)
PRIORITY_PRIMARY: bool = config["global"].get("Priority_Primary", True)

# Extract reconnection settings
SECONDARY_RECONNECTION_ENABLED: bool = config["Reconnection"]["Secondary"].get("Enabled", True)
SECONDARY_RECONNECTION_MODE: str = config["Reconnection"]["Secondary"].get("Mode", "incremental")
SECONDARY_INITIAL_DELAY: float = config["Reconnection"]["Secondary"].get("Initial_Delay", 5.0)
SECONDARY_MAX_DELAY: float = config["Reconnection"]["Secondary"].get("Max_Delay", 60.0)
SECONDARY_MAX_ATTEMPTS: int = config["Reconnection"]["Secondary"].get("Max_Attempts", 10)
SECONDARY_BACKOFF_MULTIPLIER: float = config["Reconnection"]["Secondary"].get("Backoff_Multiplier", 1.5)

# Extract connection delay settings
CONNECTION_DELAY_ENABLED: bool = config["Connection_Delay"].get("Enabled", False)
CONNECTION_DELAY_SECONDS: float = config["Connection_Delay"].get("Delay_Seconds", 5.0)
DELAY_ONLY_AFTER_BOTH: bool = config["Connection_Delay"].get("Only_After_Both", True)
DELAY_APPLY_TO: str = config["Connection_Delay"].get("Apply_To", "all")  # "all", "primary", "secondary"
DELAY_RESET_AFTER_DISCONNECT: bool = config["Connection_Delay"].get("Reset_After_Disconnect", True)

# Extract audio combiner settings
AUDIO_COMBINER_ENABLED: bool = config["AudioCombiner"].get("Enabled", False)
AUDIO_GTK_UI_ENABLED: bool = config["AudioCombiner"].get("GTK_UI", False)
AUDIO_SINK1: str = config["AudioCombiner"].get("SINK1", "sink_asha")
AUDIO_SINK2: str = config["AudioCombiner"].get("SINK2", "sink_bt")
AUDIO_COMBINED: str = config["AudioCombiner"].get("COMB", "sink_combined")
AUDIO_DESC1: str = config["AudioCombiner"].get("DESC1", "ASHA_Sink")
AUDIO_DESC2: str = config["AudioCombiner"].get("DESC2", "BT_Sink")
AUDIO_DESC3: str = config["AudioCombiner"].get("DESC3", "Combined_Sink")
AUDIO_TARGET1: str = config["AudioCombiner"].get("TARGET1", os.environ.get('ASHA_SINK', 'asha_16450405641617933895'))
AUDIO_TARGET2: str = config["AudioCombiner"].get("TARGET2", os.environ.get('BT_SINK', 'bluez_output.XX_XX_XX_XX_XX_XX.1'))
AUDIO_LAT1: int = config["AudioCombiner"].get("LAT1", int(os.environ.get('ASHA_LAT', '34')))
AUDIO_LAT2: int = config["AudioCombiner"].get("LAT2", int(os.environ.get('BT_LAT', '0')))
AUDIO_CHAN1: str = config["AudioCombiner"].get("CHAN1", "both")
AUDIO_CHAN2: str = config["AudioCombiner"].get("CHAN2", "both")
AUDIO_AUTO_ADJUST: bool = config["AudioCombiner"].get("Auto_Adjust", True)
AUDIO_MONITOR_INTERVAL: float = config["AudioCombiner"].get("Monitor_Interval", 1.0)

'''
WARNING!
DO NOT USE EASYEFFECT WITH THIS IT WILL BREAK


also it ONLY STREAMS TO DOUBLE CHANNEL BY DEFAULT using with left or right automatically will not work properly for BT devices
you can try use pwvucontrol software to control the channel
You can run this in background
'''

# Check environment variables for GTK UI
ENV_GTK_UI = os.getenv('GTK_UI', '').lower() in ['1', 'true', 'yes', 'on']

# Validate configuration
if not PRIMARY_DEVICES and not SECONDARY_DEVICES:
	raise RuntimeError("Error: No device names specified in config. Please configure at least one primary or secondary device.")

# Create combined device filters for scanning
ALL_DEVICE_FILTERS = PRIMARY_DEVICES + SECONDARY_DEVICES

# Remove empty strings from device lists
PRIMARY_DEVICES = [device for device in PRIMARY_DEVICES if device]
SECONDARY_DEVICES = [device for device in SECONDARY_DEVICES if device]
ALL_DEVICE_FILTERS = [device for device in ALL_DEVICE_FILTERS if device]

# Log configuration summary
log_info(f"Primary devices: {PRIMARY_DEVICES}")
if SECONDARY_DEVICES:
	log_info(f"Secondary devices: {SECONDARY_DEVICES}")
log_info(f"Max simultaneous devices: {MAX_DEVICES}")
if SECONDARY_RECONNECTION_ENABLED and SECONDARY_DEVICES:
	log_info(f"Secondary reconnection: {SECONDARY_RECONNECTION_MODE} mode (initial: {SECONDARY_INITIAL_DELAY}s, max: {SECONDARY_MAX_DELAY}s)")
if CONNECTION_DELAY_ENABLED:
	log_info(f"Connection delay: {CONNECTION_DELAY_SECONDS}s (only after both: {DELAY_ONLY_AFTER_BOTH}, apply to: {DELAY_APPLY_TO})", Fore.CYAN)
if AUDIO_COMBINER_ENABLED:
	log_info(f"Audio combiner enabled: {AUDIO_SINK1}+{AUDIO_SINK2} -> {AUDIO_COMBINED} (latencies: {AUDIO_LAT1}ms/{AUDIO_LAT2}ms)", Fore.MAGENTA)
	if AUDIO_GTK_UI_ENABLED or ENV_GTK_UI:
		log_info(f"GTK UI enabled for audio combiner", Fore.CYAN)

# GATT Configuration - Separate UUID for secondary devices
GATT_ATTRIBUTE: str = config["GATT"]["Volume"]["ID"] or "00e4ca9e-ab14-41e4-8823-f9e70c7e91df"
GATT_ATTRIBUTE_SEC: str = config["GATT"]["Volume_Sec"]["ID"] or "00e4ca9e-ab14-41e4-8823-f9e70c7e91df"
PER_DEVICE_VOLUME: bool = config["GATT"].get("Per_Device_Volume", True)

# Global
SEPARATE_BOOLEAN = config["global"].get("Separate_boolean", False)
Filter_DFU = config["global"].get("Filter_DFU", False)

# ASHA sink repository settings
REPO_URL: str = "https://github.com/thewierdnut/asha_pipewire_sink.git"
CLONE_DIR: str = os.path.expanduser("~/asha_pipewire_sink")
BUILD_DIR: str = os.path.join(CLONE_DIR, "build")
EXECUTABLE: str = os.path.join(BUILD_DIR, "asha_pipewire_sink")

# Randomized timing settings
RETRY_DELAY: float = random.uniform(0.4, 1.0)
DEFAULT_RETRY_INTERVAL: float = 0.0
MAX_TIMEOUT: float = random.uniform(600, 1200)
Timeout_qs: float = random.uniform(80000, 100000)

# Blacklist devices to avoid
BLACKLIST: list = config.get("Blacklist", [])

# ------------------------------
# THREAD-SAFE GLOBAL STATE
# ------------------------------
# All access MUST use global_lock
processed_devices: Set[str] = set()
connected_devices: Dict[str, Dict] = {}  # mac -> {name, volume, last_seen, device_type, priority}

# Threading & process events (thread-safe by design)
shutdown_evt = threading.Event()
reconnect_evt = threading.Event()
reset_evt = threading.Event()
asha_restart_evt = threading.Event()

# ASHA process state (protected by global_lock)
asha_handle: Optional[Tuple[int, int]] = None
asha_started: bool = False

# Legacy-style connection tracking (simpler approach)
primary_connection_in_progress = threading.Event()
secondary_connection_in_progress = threading.Event()

# Secondary device reconnection tracking
secondary_reconnection_attempts: Dict[str, Dict[str, Any]] = {}  # mac -> {attempts: int, next_delay: float, last_attempt: float}

# Connection delay tracking
connection_delay_active = threading.Event()
connection_delay_start_time = 0.0
connection_delay_timer: Optional[threading.Timer] = None

# Audio combiner state
audio_combiner_started = threading.Event()
audio_combiner_thread: Optional[threading.Thread] = None
audio_combiner_stop = threading.Event()
audio_combiner_manager: Optional[Any] = None

# GTK UI state
gtk_ui_thread: Optional[threading.Thread] = None
gtk_ui_stop = threading.Event()
gtk_window = None
gtk_latency_queue = queue.Queue()

# ------------------------------
# ASYNC EVENT LOOP MANAGEMENT
# ------------------------------
class AsyncEventLoopManager:
	"""Thread-safe async event loop management"""
	def __init__(self):
		self.loop: Optional[asyncio.AbstractEventLoop] = None
		self.thread: Optional[threading.Thread] = None
		self._started = False
		
	def start(self):
		"""Start the async event loop in a dedicated thread"""
		with global_lock:
			if self._started:
				return
				
			self.loop = asyncio.new_event_loop()
			self.thread = threading.Thread(target=self._run_loop, daemon=True)
			self.thread.start()
			self._started = True
			log_info("Async event loop started")
			
	def _run_loop(self):
		"""Run the event loop (to be called in dedicated thread)"""
		asyncio.set_event_loop(self.loop)
		try:
			self.loop.run_forever()
		finally:
			self.loop.close()
			
	def stop(self):
		"""Stop the async event loop"""
		with global_lock:
			if not self._started or not self.loop:
				return
				
			self.loop.call_soon_threadsafe(self.loop.stop)
			if self.thread:
				self.thread.join(timeout=5.0)
			self._started = False
			log_info("Async event loop stopped")
			
	def run_coroutine_threadsafe(self, coro):
		"""Run a coroutine in a thread-safe manner"""
		if not self._started or not self.loop:
			raise RuntimeError("Async event loop not started")
		return asyncio.run_coroutine_threadsafe(coro, self.loop)

# Global async manager
async_manager = AsyncEventLoopManager()

# ------------------------------
# AUDIO COMBINER CLASSES
# ------------------------------
class Sink:
	__slots__ = ('name','target','desc','channel','latency','loopback_id','module_id','orig_volume')
	def __init__(self, name: str, target: str, desc: str, channel: str = 'both', latency: int = 0):
		self.name = name
		self.target = target
		self.desc = desc
		self.channel = channel
		self.latency = int(latency)
		self.loopback_id: Optional[str] = None
		self.module_id: Optional[str] = None
		self.orig_volume: Optional[str] = None

	def create_null_sink(self) -> Optional[str]:
		if self.module_id:
			log_debug("Null sink already created: %s", self.name)
			return self.module_id
		module_id = run_cmd([
			'pactl', 'load-module', 'module-null-sink',
			f'sink_name={self.name}', f'sink_properties=device.description={self.desc}'
		], capture=True)
		if module_id:
			self.module_id = module_id
			log_audio(f"Created null sink {self.name} (module {module_id})")
		else:
			log_error(f"Failed to create null sink {self.name}")
		return self.module_id

	def _build_loopback_cmd(self) -> List[str]:
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
		return cmd

	def create_loopback(self) -> Optional[str]:
		if self.loopback_id:
			log_debug("Loopback already present for %s (%s), cleaning up before recreate", self.name, self.loopback_id)
			self.cleanup_loopback()
		module_id = run_cmd(self._build_loopback_cmd(), capture=True)
		if module_id:
			self.loopback_id = module_id
			log_audio(f"Created loopback {self.name} -> {self.target} (module {module_id}) latency={self.latency}ms")
		else:
			log_error(f"Failed to create loopback for {self.name} -> {self.target}")
		return self.loopback_id

	def cleanup_loopback(self) -> None:
		if not self.loopback_id:
			return
		for attempt in range(3):
			run_cmd(['pactl', 'unload-module', self.loopback_id], check=False)
			time.sleep(0.05 * (attempt + 1))
			modules = run_cmd(['pactl', 'list', 'short', 'modules'], capture=True)
			if not modules or self.loopback_id not in modules:
				break
			log_debug("Loopback %s still present after attempt %d", self.loopback_id, attempt + 1)
		else:
			log_warning("Loopback %s could not be removed after retries", self.loopback_id)
		self.loopback_id = None

	def get_volume(self) -> str:
		out = run_cmd(['pactl', 'get-sink-volume', self.target], capture=True)
		if not out:
			self.orig_volume = '100%'
			return self.orig_volume
		for line in out.splitlines():
			if 'Volume:' in line:
				for tok in reversed(line.split()):
					if tok.endswith('%'):
						self.orig_volume = tok
						return self.orig_volume
		self.orig_volume = '100%'
		return self.orig_volume

	def set_volume(self, vol: str) -> None:
		if not vol:
			return
		run_cmd(['pactl', 'set-sink-volume', self.target, vol], check=False)

	def cleanup(self) -> None:
		try:
			self.cleanup_loopback()
		except Exception as e:
			log_debug("cleanup_loopback error: %s", e)
		if self.module_id:
			run_cmd(['pactl', 'unload-module', self.module_id], check=False)
			self.module_id = None
		if self.orig_volume:
			try:
				self.set_volume(self.orig_volume)
			except Exception:
				log_warning(f"Could not restore volume for {self.target}")

class CombinedSink:
	__slots__ = ('name','slaves','desc','module_id')
	def __init__(self, name: str, slaves: List[str], desc: str):
		self.name = name
		self.slaves = list(slaves)
		self.desc = desc
		self.module_id: Optional[str] = None

	def create(self, volume: Optional[str] = None) -> Optional[str]:
		self.module_id = run_cmd([
			'pactl', 'load-module', 'module-combine-sink',
			f'sink_name={self.name}',
			f'slaves={",".join(self.slaves)}',
			f'sink_properties=device.description={self.desc}'
		], capture=True)
		if self.module_id:
			run_cmd(['pactl', 'set-default-sink', self.name], check=False)
			if volume:
				run_cmd(['pactl', 'set-sink-volume', self.name, volume], check=False)
			log_audio(f"Created combined sink {self.name} (module {self.module_id})")
		else:
			log_error(f"Failed to create combined sink {self.name}")
		return self.module_id

	def update_slaves(self, new_slaves: List[str]) -> None:
		self.slaves = list(new_slaves)
		run_cmd(['pactl', 'set-sink-slaves', self.name, ','.join(self.slaves)], check=False)
		log_debug(f"Updated combined sink {self.name} slaves -> {self.slaves}")

	def cleanup(self) -> None:
		if self.module_id:
			run_cmd(['pactl', 'unload-module', self.module_id], check=False)
			self.module_id = None

class AudioCombinerManager:
	"""Manages audio sink combining for ASHA and BT devices"""
	
	def __init__(self, config: Dict[str, Any]):
		self.config = config
		# Get latencies from config (not from environment at this point)
		lat1 = config.get('LAT1', AUDIO_LAT1)
		lat2 = config.get('LAT2', AUDIO_LAT2)
		
		self.sink1 = Sink(
			config['SINK1'], 
			config['TARGET1'], 
			config['DESC1'], 
			config.get('CHAN1', 'both'), 
			int(lat1)
		)
		self.sink2 = Sink(
			config['SINK2'], 
			config['TARGET2'], 
			config['DESC2'], 
			config.get('CHAN2', 'both'), 
			int(lat2)
		)
		self.comb_sink = CombinedSink(
			config['COMB'], 
			[self.sink1.name, self.sink2.name], 
			config['DESC3']
		)
		self._cached_sinks: Set[str] = set()
		self.monitor_thread: Optional[threading.Thread] = None
		self._last_config_lat1 = lat1
		self._last_config_lat2 = lat2
		
	def _refresh_sink_cache(self) -> Set[str]:
		"""Refresh cache of available audio sinks"""
		out = run_cmd(['pactl', 'list', 'short', 'sinks'], capture=True)
		current: Set[str] = set()
		if out:
			for line in out.splitlines():
				parts = line.split()
				if len(parts) >= 2:
					current.add(parts[1])
		self._cached_sinks = current
		# log_debug(f"Refreshed sink cache: {current}")
		return current
	
	def wait_for_sink_target(self, target: str, timeout: float = 30.0) -> bool:
		"""Wait for a specific audio sink to become available"""
		deadline = time.monotonic() + timeout
		sinks = self._refresh_sink_cache()
		if target in sinks:
			return True
		
		log_audio(f"Waiting for sink {target}...")
		while time.monotonic() < deadline and not audio_combiner_stop.is_set():
			sinks = self._refresh_sink_cache()
			if target in sinks:
				log_audio(f"Sink {target} detected")
				return True
			time.sleep(0.5)
		
		log_warning(f"Timeout waiting for sink {target}")
		return False
	
	def cleanup_zombie_modules(self) -> None:
		"""Clean up any zombie audio modules"""
		modules = run_cmd(['pactl', 'list', 'short', 'modules'], capture=True)
		if not modules:
			return
		current_loopbacks = {self.sink1.loopback_id, self.sink2.loopback_id}
		for line in modules.splitlines():
			if 'module-loopback' in line:
				parts = line.split()
				if not parts:
					continue
				module_id = parts[0]
				if module_id in current_loopbacks:
					continue
				if self.sink1.name in line or self.sink2.name in line:
					log_warning(f"Unloading zombie loopback module {module_id}")
					run_cmd(['pactl', 'unload-module', module_id], check=False)
					time.sleep(0.02)
	
	def monitor_loop(self) -> None:
		"""Monitor audio sinks and adjust as needed"""
		log_audio("Starting audio combiner monitor loop (session-only latencies)")
		self._refresh_sink_cache()
		
		while not audio_combiner_stop.is_set():
			try:
				# Check if both sinks are still available
				sinks = self._refresh_sink_cache()
				
				# Handle ASHA sink removal
				if self.sink1.target in sinks and not self.sink1.loopback_id:
					self.sink1.create_loopback()
					slaves = [self.sink1.name] + ([self.sink2.name] if self.sink2.loopback_id else [])
					self.comb_sink.update_slaves(slaves)
				
				# Handle BT sink removal/addition
				if self.sink2.target in sinks and not self.sink2.loopback_id:
					self.sink2.create_loopback()
					self.comb_sink.update_slaves([self.sink1.name, self.sink2.name])
				
				# Check for latency updates from GTK UI (session-only)
				try:
					while not gtk_latency_queue.empty():
						lat1, lat2 = gtk_latency_queue.get_nowait()
						log_audio(f"Received latency update from GTK UI (session-only): {lat1}ms, {lat2}ms")
						self.set_latencies(lat1, lat2)
				except queue.Empty:
					pass
				
				# Clean up zombies periodically
				if time.monotonic() % 10 < 1:  # Every ~10 seconds
					self.cleanup_zombie_modules()
				
				time.sleep(self.config.get('Monitor_Interval', 1.0))
				
			except Exception as e:
				log_error(f"Audio monitor error: {e}")
				time.sleep(2.0)
	
	def set_latencies(self, lat1_ms: int, lat2_ms: int, force_update: bool = True) -> None:
		"""Update audio sink latencies without saving to config file"""
		# Only update if values actually changed
		if self.sink1.latency == lat1_ms and self.sink2.latency == lat2_ms and not force_update:
			log_debug("Latencies unchanged, skipping update")
			return
			
		log_audio(f"Updating latencies: sink1={lat1_ms}ms sink2={lat2_ms}ms (session only)")
		
		# Store the new values
		self.sink1.latency = int(lat1_ms)
		self.sink2.latency = int(lat2_ms)
		
		# DO NOT update config dictionary - session only
		# DO NOT call save_config()
		
		# Update environment variables for current session
		os.environ['ASHA_LAT'] = str(lat1_ms)
		os.environ['BT_LAT'] = str(lat2_ms)
		
		# Only recreate loopbacks if they exist
		if self.sink1.loopback_id:
			self.sink1.cleanup_loopback()
			self.sink1.create_loopback()
		
		if self.sink2.loopback_id:
			self.sink2.cleanup_loopback()
			self.sink2.create_loopback()
		
		# Update combined sink slaves if it exists
		if self.comb_sink.module_id:
			slaves = [self.sink1.name] + ([self.sink2.name] if self.sink2.loopback_id else [])
			self.comb_sink.update_slaves(slaves)
	
	def get_latencies(self) -> Tuple[int, int]:
		"""Get current latencies"""
		return self.sink1.latency, self.sink2.latency
	
	def start(self) -> bool:
		"""Start the audio combiner"""
		try:
			log_audio("Starting audio combiner (GTK UI changes are session-only)...")
			
			# Get original default sink
			orig_default_sink = run_cmd(['pactl', 'get-default-sink'], capture=True) or ''
			
			# Wait for sinks to be available
			if not self.wait_for_sink_target(self.sink1.target, timeout=20.0):
				log_warning(f"ASHA sink {self.sink1.target} not found")
				return False
			
			if not self.wait_for_sink_target(self.sink2.target, timeout=20.0):
				log_warning(f"BT sink {self.sink2.target} not found (may connect later)")
			
			# Get original volumes
			vol1 = self.sink1.get_volume()
			vol2 = self.sink2.get_volume()

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
			
			# Set combined sink as default
			run_cmd(['pactl', 'set-default-sink', self.comb_sink.name], check=False)
			
			# Restore volumes
			self.sink1.set_volume('100%')
			self.sink2.set_volume('100%')
			
			log_audio(f"Audio combiner ready. Original volumes: {vol1} / {vol2}")
			log_audio(f"Original default sink: {orig_default_sink}")
			log_audio("Note: GTK UI latency changes are session-only and will not persist")
			
			# Start monitor thread
			self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
			self.monitor_thread.start()
			
			# Set global audio combiner manager
			global audio_combiner_manager
			audio_combiner_manager = self
			
			audio_combiner_started.set()
			return True
			
		except Exception as e:
			log_error(f"Failed to start audio combiner: {e}")
			return False
	
	def stop(self) -> None:
		"""Stop the audio combiner"""
		log_audio("Stopping audio combiner...")
		audio_combiner_stop.set()
		
		if self.monitor_thread and self.monitor_thread.is_alive():
			self.monitor_thread.join(timeout=2.0)
		
		try:
			self.cleanup_zombie_modules()
		except Exception:
			pass
		
		try:
			self.comb_sink.cleanup()
			self.sink1.cleanup()
			self.sink2.cleanup()
		except Exception as e:
			log_debug(f"Cleanup exception: {e}")
		
		# Clear global reference
		global audio_combiner_manager
		audio_combiner_manager = None
		
		log_audio("Audio combiner stopped")

# ------------------------------
# GTK UI CLASS (GTK4 VERSION)
# ------------------------------
class GtkLatencyUI:
    def __init__(self):
        self.app = None
        self.window = None
        self.spin1 = None
        self.spin2 = None
        self.status_label = None
        self.running = False

    def run(self):
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk, GLib
        
        class LatencyApp(Gtk.Application):
            def __init__(self):
                super().__init__(application_id="org.example.latencyui")
                self.window = None
                self.spin1 = None
                self.spin2 = None
                self.status_label = None
                
            def do_activate(self):
                # Create the main window
                self.window = Gtk.ApplicationWindow(application=self)
                self.window.set_title("Adjust Sink Latencies (ms) - Session Only")
                self.window.set_default_size(400, 180)
                self.window.set_resizable(True)
                
                # Main vertical box
                vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                vbox.set_margin_top(12)
                vbox.set_margin_bottom(12)
                vbox.set_margin_start(12)
                vbox.set_margin_end(12)
                self.window.set_child(vbox)
                
                # Create grid for controls
                grid = Gtk.Grid()
                grid.set_row_spacing(6)
                grid.set_column_spacing(12)
                grid.set_halign(Gtk.Align.CENTER)
                vbox.append(grid)
                
                # Labels
                label1 = Gtk.Label(label="Sink 1 (ASHA) latency (ms):")
                label1.set_halign(Gtk.Align.START)
                
                label2 = Gtk.Label(label="Sink 2 (BT) latency (ms):")
                label2.set_halign(Gtk.Align.START)
                
                # Spin buttons
                self.spin1 = Gtk.SpinButton.new_with_range(0, 2000, 1)
                self.spin1.set_value(AUDIO_LAT1)
                self.spin1.set_hexpand(True)
                
                self.spin2 = Gtk.SpinButton.new_with_range(0, 2000, 1)
                self.spin2.set_value(AUDIO_LAT2)
                self.spin2.set_hexpand(True)
                
                # Status label
                self.status_label = Gtk.Label(
                    label=f"Current: ASHA={AUDIO_LAT1}ms, BT={AUDIO_LAT2}ms (session only)"
                )
                self.status_label.set_halign(Gtk.Align.CENTER)
                
                # Attach widgets to grid
                grid.attach(label1, 0, 0, 1, 1)
                grid.attach(self.spin1, 1, 0, 1, 1)
                grid.attach(label2, 0, 1, 1, 1)
                grid.attach(self.spin2, 1, 1, 1, 1)
                grid.attach(self.status_label, 0, 2, 2, 1)
                
                # Button box
                button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                button_box.set_halign(Gtk.Align.END)
                button_box.set_margin_top(12)
                vbox.append(button_box)
                
                # Buttons
                reset_btn = Gtk.Button(label="Reset to defaults")
                apply_btn = Gtk.Button(label="Apply (Session Only)")
                close_btn = Gtk.Button(label="Close UI")
                
                reset_btn.connect("clicked", self.on_reset_to_defaults)
                apply_btn.connect("clicked", self.on_apply)
                close_btn.connect("clicked", self.on_close)
                
                button_box.append(reset_btn)
                button_box.append(apply_btn)
                button_box.append(close_btn)
                
                # Connect window close event
                self.window.connect("close-request", self.on_close_request)
                
                # Present the window
                self.window.present()
                
                # Store references in the outer class
                ui.window = self.window
                ui.spin1 = self.spin1
                ui.spin2 = self.spin2
                ui.status_label = self.status_label
                ui.running = True
                
                # Start periodic update
                GLib.timeout_add_seconds(2, self.update_latencies)
                
                # Check for stop signal
                GLib.timeout_add(500, self.check_stop)
            
            def on_apply(self, btn):
                if not self.spin1 or not self.spin2:
                    return
                lat1 = int(self.spin1.get_value())
                lat2 = int(self.spin2.get_value())
                gtk_latency_queue.put((lat1, lat2))
                
                os.environ["ASHA_LAT"] = str(lat1)
                os.environ["BT_LAT"] = str(lat2)
                
                if self.status_label:
                    self.status_label.set_label(
                        f"Current: ASHA={lat1}ms, BT={lat2}ms (session only)"
                    )
            
            def on_reset_to_defaults(self, btn):
                if self.spin1:
                    self.spin1.set_value(34)
                if self.spin2:
                    self.spin2.set_value(0)
                self.on_apply(btn)
            
            def on_close(self, btn):
                global gtk_ui_stop
                gtk_ui_stop.set()
                if self.window:
                    self.window.close()
            
            def on_close_request(self, window):
                global gtk_ui_stop
                gtk_ui_stop.set()
                return False  # Allow window to close
            
            def update_latencies(self):
                if audio_combiner_manager and not gtk_ui_stop.is_set():
                    try:
                        lat1, lat2 = audio_combiner_manager.get_latencies()
                        
                        if self.spin1 and not self.spin1.has_focus():
                            self.spin1.set_value(lat1)
                        if self.spin2 and not self.spin2.has_focus():
                            self.spin2.set_value(lat2)
                        
                        if self.status_label:
                            self.status_label.set_label(
                                f"Current: ASHA={lat1}ms, BT={lat2}ms (session only)"
                            )
                    except Exception as e:
                        log_debug(f"Error updating latencies: {e}")
                
                return not gtk_ui_stop.is_set()  # Continue if not stopped
            
            def check_stop(self):
                if gtk_ui_stop.is_set():
                    if self.window:
                        self.window.close()
                    ui.running = False
                    return False
                return True
        
        # Create and run the application
        ui = self
        app = LatencyApp()
        self.app = app
        
        # Run the application
        app.run(None)


def start_gtk_ui():
    """Start GTK UI in a separate thread"""
    global gtk_ui_thread
    if gtk_ui_thread and gtk_ui_thread.is_alive():
        log_gtk("GTK UI already running")
        return
    
    gtk_ui_stop.clear()
    gtk_ui_thread = threading.Thread(target=_gtk_ui_worker, daemon=True)
    gtk_ui_thread.start()
    log_gtk("GTK UI thread started")

def _gtk_ui_worker():
    """Worker function for GTK UI thread"""
    # Set the GTK thread name for debugging
    threading.current_thread().name = "GTK-UI-Thread"
    
    # Create and run the UI
    gtk_ui = GtkLatencyUI()
    try:
        gtk_ui.run()
    except Exception as e:
        log_error(f"GTK UI error: {e}")
    finally:
        log_gtk("GTK UI thread exiting")

def stop_gtk_ui():
    """Stop GTK UI"""
    global gtk_ui_thread
    gtk_ui_stop.set()
    if gtk_ui_thread and gtk_ui_thread.is_alive():
        gtk_ui_thread.join(timeout=2.0)
        gtk_ui_thread = None
    log_gtk("GTK UI stopped")

# ------------------------------
# PROCESS MANAGEMENT UTILITIES
# ------------------------------
def run_cmd(cmd: List[str], capture: bool = False, check: bool = True, timeout: Optional[float] = None) -> Optional[str]:
	"""Run a command and return output if requested"""
	try:
		if capture:
			res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=check, timeout=timeout)
			return res.stdout.strip()
		else:
			subprocess.run(cmd, check=check, timeout=timeout)
			return None
	except subprocess.CalledProcessError as e:
		if capture:
			log_debug(f"Command failed (capture): {' '.join(cmd)} -> {getattr(e, 'output', '')}")
			return ""
		log_warning(f"Command failed: {' '.join(cmd)}")
		return None
	except subprocess.TimeoutExpired:
		log_warning(f"Command timeout: {' '.join(cmd)}")
		return "" if capture else None

def run_command(command: str, check: bool = True, capture_output: bool = False,
				input_text: Optional[str] = None, cwd: Optional[str] = None,
				debug: bool = True) -> Optional[str]:
	"""Run a shell command and return output if requested"""
	if debug and DEBUG:
		log_debug(f"Running command: {command} [cwd={cwd}]")
	try:
		result = subprocess.run(
			command,
			shell=True,
			check=check,
			text=True,
			capture_output=capture_output,
			input=input_text,
			cwd=cwd
		)
		return result.stdout.strip() if capture_output else None
	except subprocess.CalledProcessError as e:
		if debug:
			log_error(f"Command error: {e}")
		if capture_output and e.stdout:
			return e.stdout.strip()
		return None

def is_asha_process_running() -> bool:
	"""Check if ASHA sink process is already running"""
	with global_lock:
		try:
			for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
				try:
					if (proc.info['name'] and 'asha_pipewire_sink' in proc.info['name'].lower()):
						return True
					if (proc.info['cmdline'] and 
						any('asha_pipewire_sink' in str(cmd).lower() for cmd in proc.info['cmdline'])):
						return True
				except (psutil.NoSuchProcess, psutil.AccessDenied):
					continue
		except Exception as e:
			log_warning(f"Process check failed: {e}")
		return False

def kill_existing_asha_processes() -> None:
	"""Forcefully kill any existing ASHA sink processes"""
	with global_lock:
		try:
			for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
				try:
					if (proc.info['cmdline'] and 
						any('asha_pipewire_sink' in str(cmd).lower() for cmd in proc.info['cmdline'])):
						log_warning(f"Killing existing ASHA process: {proc.info['pid']}")
						os.kill(proc.info['pid'], signal.SIGKILL)
						time.sleep(0.5)
				except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
					continue
		except Exception as e:
			log_error(f"Error killing existing processes: {e}")

# ------------------------------
# UTILITY FUNCTIONS
# ------------------------------
def run_trust_background(mac: str) -> None:
	"""Launch `bluetoothctl trust <MAC>` in the background non-blocking"""
	try:
		subprocess.Popen(
			["bluetoothctl", "trust", mac],
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
		)
	except Exception as e:
		log_warning(f"Failed to run bluetoothctl trust for {mac}: {e}")

def run_pair_devices(mac: str) -> None:
	"""Launch `bluetoothctl pair <MAC>` in the background non-blocking"""
	try:
		subprocess.Popen(
			["bluetoothctl", "pair", mac],
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
		)
	except Exception as e:
		log_warning(f"Failed to run bluetoothctl pair for {mac}: {e}")
		
def run_remove_devices(mac: str) -> None:
	"""Launch `bluetoothctl remove <MAC>` in the background non-blocking"""
	try:
		subprocess.Popen(
			["bluetoothctl", "remove", mac],
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
		)
	except Exception as e:
		log_warning(f"Failed to run bluetoothctl remove for {mac}: {e}")

def disable_pairable_background() -> None:
	"""Launch `bluetoothctl pairable off` in the background non-blocking"""
	try:
		subprocess.Popen(
			["bluetoothctl", "pairable", "off"],
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
		)
	except Exception as e:
		log_warning(f"Failed to run bluetoothctl pairable off: {e}")

# ------------------------------
# CONNECTION DELAY MANAGER
# ------------------------------
class ConnectionDelayManager:
	"""Manages connection delays after device connections"""
	
	def __init__(self):
		self.delay_enabled = CONNECTION_DELAY_ENABLED
		self.delay_seconds = CONNECTION_DELAY_SECONDS
		self.only_after_both = DELAY_ONLY_AFTER_BOTH
		self.apply_to = DELAY_APPLY_TO
		self.reset_after_disconnect = DELAY_RESET_AFTER_DISCONNECT
		
	def should_apply_delay(self, device_type: str, device_manager) -> bool:
		"""Check if delay should be applied for this connection"""
		if not self.delay_enabled:
			return False
			
		# Check if device type matches apply_to filter
		if self.apply_to != "all":
			if self.apply_to == "primary" and device_type != "primary":
				return False
			elif self.apply_to == "secondary" and device_type != "secondary":
				return False
		
		# Check if we only apply delay after both devices are connected
		if self.only_after_both:
			# Get connection counts
			primary_count = device_manager.get_connected_primary_count()
			secondary_count = device_manager.get_connected_secondary_count()
			
			# Check if we have at least one of each type
			has_both = primary_count >= 1 and secondary_count >= 1
			
			# If we don't have both types yet, no delay
			if not has_both:
				log_delay(f"No delay: don't have both device types yet (primary: {primary_count}, secondary: {secondary_count})")
				return False
		
		# Check if delay is already active
		if connection_delay_active.is_set():
			log_delay(f"Delay already active, skipping additional delay")
			return False
			
		return True
	
	def start_delay(self, device_type: str, device_manager):
		"""Start a connection delay"""
		if not self.should_apply_delay(device_type, device_manager):
			return
			
		log_delay(f"Starting {self.delay_seconds}s connection delay after {device_type} device connection")
		
		# Set the delay active
		connection_delay_active.set()
		global connection_delay_start_time
		connection_delay_start_time = time.time()
		
		# Create a timer to clear the delay
		def clear_delay():
			connection_delay_active.clear()
			log_delay(f"Connection delay completed after {self.delay_seconds}s")
		
		global connection_delay_timer
		if connection_delay_timer:
			connection_delay_timer.cancel()
		
		connection_delay_timer = threading.Timer(self.delay_seconds, clear_delay)
		connection_delay_timer.daemon = True
		connection_delay_timer.start()
	
	def check_delay(self) -> bool:
		"""Check if delay is currently active"""
		if not self.delay_enabled:
			return False
			
		return connection_delay_active.is_set()
	
	def get_remaining_delay(self) -> float:
		"""Get remaining delay time in seconds"""
		if not connection_delay_active.is_set():
			return 0.0
			
		elapsed = time.time() - connection_delay_start_time
		remaining = max(0, self.delay_seconds - elapsed)
		return remaining
	
	def reset_delay(self):
		"""Reset any active delay"""
		if connection_delay_active.is_set():
			connection_delay_active.clear()
			global connection_delay_timer
			if connection_delay_timer:
				connection_delay_timer.cancel()
				connection_delay_timer = None
			log_delay("Connection delay reset")
	
	def handle_device_disconnect(self, device_type: str, device_manager):
		"""Handle device disconnection for delay reset logic"""
		if not self.delay_enabled or not self.reset_after_disconnect:
			return
			
		# Check if we still have both device types
		primary_count = device_manager.get_connected_primary_count()
		secondary_count = device_manager.get_connected_secondary_count()
		
		# If we no longer have both types, reset delay
		if self.only_after_both and not (primary_count >= 1 and secondary_count >= 1):
			self.reset_delay()
			log_delay(f"Delay reset: no longer have both device types (primary: {primary_count}, secondary: {secondary_count})")

# Initialize connection delay manager
connection_delay_manager = ConnectionDelayManager()

# ------------------------------
# SECONDARY DEVICE RECONNECTION MANAGER
# ------------------------------
class SecondaryReconnectionManager:
	"""Manages reconnection attempts for secondary devices without restarting Bluetooth"""
	
	def __init__(self):
		self.reconnection_threads: Dict[str, threading.Thread] = {}
		self.reconnection_events: Dict[str, threading.Event] = {}
		
	def should_attempt_reconnection(self, mac: str, name: str, enabled: bool) -> bool:
		"""Check if we should attempt reconnection for this secondary device"""
		if not enabled:
			log_reconnection(f"Secondary reconnection disabled, skipping {name}")
			return False
			
		with global_lock:
			if mac in secondary_reconnection_attempts:
				attempt_info = secondary_reconnection_attempts[mac]
				if attempt_info['attempts'] >= SECONDARY_MAX_ATTEMPTS:
					log_reconnection(f"Max reconnection attempts ({SECONDARY_MAX_ATTEMPTS}) reached for {name}, giving up")
					return False
					
				# Check if enough time has passed since last attempt
				time_since_last = time.time() - attempt_info['last_attempt']
				if time_since_last < attempt_info['next_delay']:
					return False
			else:
				# First attempt
				secondary_reconnection_attempts[mac] = {
					'attempts': 0,
					'next_delay': SECONDARY_INITIAL_DELAY,
					'last_attempt': 0
				}
				
		return True
	
	def update_reconnection_attempt(self, mac: str, success: bool) -> None:
		"""Update reconnection attempt counter and calculate next delay"""
		with global_lock:
			if mac not in secondary_reconnection_attempts:
				return
				
			if success:
				# Reset on successful reconnection
				del secondary_reconnection_attempts[mac]
				if mac in self.reconnection_events:
					self.reconnection_events[mac].set()  # Stop reconnection thread
			else:
				attempt_info = secondary_reconnection_attempts[mac]
				attempt_info['attempts'] += 1
				attempt_info['last_attempt'] = time.time()
				
				# Calculate next delay based on mode
				if SECONDARY_RECONNECTION_MODE == "incremental":
					next_delay = attempt_info['next_delay'] * SECONDARY_BACKOFF_MULTIPLIER
					attempt_info['next_delay'] = min(next_delay, SECONDARY_MAX_DELAY)
				elif SECONDARY_RECONNECTION_MODE == "constant":
					attempt_info['next_delay'] = SECONDARY_INITIAL_DELAY
				else:  # exponential
					next_delay = SECONDARY_INITIAL_DELAY * (SECONDARY_BACKOFF_MULTIPLIER ** attempt_info['attempts'])
					attempt_info['next_delay'] = min(next_delay, SECONDARY_MAX_DELAY)
	
	def start_reconnection_attempt(self, mac: str, name: str, device_manager, enabled: bool) -> None:
		"""Start a reconnection attempt for a secondary device"""
		if not self.should_attempt_reconnection(mac, name, enabled):
			return
			
		# Stop any existing reconnection thread for this device
		if mac in self.reconnection_events:
			self.reconnection_events[mac].set()
			
		# Create new event for this reconnection attempt
		stop_event = threading.Event()
		self.reconnection_events[mac] = stop_event
		
		# Start reconnection thread
		thread = threading.Thread(
			target=self._reconnection_worker,
			args=(mac, name, device_manager, stop_event, enabled),
			daemon=True
		)
		self.reconnection_threads[mac] = thread
		thread.start()
		
		log_reconnection(f"Started reconnection attempt for {name} (MAC: {mac})")
	
	def _reconnection_worker(self, mac: str, name: str, device_manager, stop_event: threading.Event, enabled: bool) -> None:
		"""Worker thread for reconnecting to a secondary device"""
		attempt_info = secondary_reconnection_attempts.get(mac, {})
		attempt_count = attempt_info.get('attempts', 0) + 1
		next_delay = attempt_info.get('next_delay', SECONDARY_INITIAL_DELAY)
		
		log_reconnection(f"Reconnection attempt {attempt_count}/{SECONDARY_MAX_ATTEMPTS} for {name} in {next_delay:.1f}s")
		
		# Wait for the calculated delay
		if stop_event.wait(next_delay):
			log_reconnection(f"Reconnection attempt for {name} cancelled")
			return
			
		if shutdown_evt.is_set():
			return
			
		# Attempt reconnection
		log_reconnection(f"Attempting to reconnect to {name} (attempt {attempt_count})")
		
		try:
			# Use the same connection logic as initial connection
			future = async_manager.run_coroutine_threadsafe(
				self._async_reconnect_attempt(mac, name, device_manager)
			)
			success = future.result(timeout=MAX_TIMEOUT + 10)
		except Exception as e:
			log_error(f"Async reconnection failed for {name}: {e}")
			success = False
		
		# Update reconnection attempt counter
		self.update_reconnection_attempt(mac, success)
		
		if success:
			log_reconnection(f"Successfully reconnected to {name}")
			device_manager.add_connected_device(mac, name)
			
			# Execute GATT operations for the reconnected device
			log_gatt(f"Executing GATT operations for reconnected secondary device {name}")
			time.sleep(1)
			self._execute_secondary_gatt_operations(mac, name)
		else:
			log_warning(f"Reconnection attempt {attempt_count} failed for {name}")
			
			# Schedule next attempt if we haven't reached max attempts and feature is still enabled
			if self.should_attempt_reconnection(mac, name, enabled):
				log_reconnection(f"Scheduling next reconnection attempt for {name} in {secondary_reconnection_attempts[mac]['next_delay']:.1f}s")
				self.start_reconnection_attempt(mac, name, device_manager, enabled)
	
	async def _async_reconnect_attempt(self, mac: str, name: str, device_manager) -> bool:
		"""Asynchronous reconnection attempt for secondary device"""
		if not re.match(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$', mac):
			log_debug(f"Invalid MAC address in reconnection attempt: {mac}")
			return False

		attempts = 0
		while not shutdown_evt.is_set() and attempts < 2:
			try:
				output = await asyncio.to_thread(
					run_command,
					f"bluetoothctl connect {mac}",
					capture_output=True
				)

				if output and any(s in output for s in ["Connection successful", "already connected"]):
					time.sleep(1)
					info = await asyncio.to_thread(
						run_command,
						f"bluetoothctl info {mac}",
						capture_output=True
					)
					if info and "Connected: yes" in info:
						return True

				log_warning(f"Reconnect attempt {attempts + 1} failed for secondary device {name}")

			except Exception as e:
				log_error(f"Reconnection attempt exception for {name}: {e}")

			attempts += 1
			await asyncio.sleep(DEFAULT_RETRY_INTERVAL)

		return False
	
	def _execute_secondary_gatt_operations(self, mac: str, name: str) -> None:
		"""Execute GATT operations for reconnected secondary device"""
		try:
			log_gatt(f"Executing bluetoothctl connect for reconnected secondary device {name}")
			
			connect_output = run_command(f"bluetoothctl connect {mac}", capture_output=True)
			if connect_output and "Connection successful" in connect_output:
				time.sleep(0.5)
				
				log_gatt(f"Executing GATT operations for reconnected secondary device {name}")
				
				process = subprocess.Popen(
					["bluetoothctl"],
					stdin=subprocess.PIPE,
					stdout=subprocess.PIPE,
					stderr=subprocess.PIPE,
					text=True
				)
				
				volume_value = config["GATT"]["Volume_Sec"]["Value"]
				commands = f"""connect {mac}
gatt.select-attribute {GATT_ATTRIBUTE_SEC}
gatt.write {volume_value}
exit
"""
				stdout, stderr = process.communicate(commands)
				if process.returncode == 0:
					log_gatt(f"Secondary GATT operations completed for reconnected {name}")
				else:
					log_error(f"Secondary GATT operations failed for reconnected {name}: {stderr.strip()}")
			else:
				log_warning(f"Failed to connect to reconnected secondary device {name} via bluetoothctl")
				
		except Exception as e:
			log_error(f"Error executing secondary GATT operations for reconnected {name}: {e}")
	
	def stop_all_reconnections(self) -> None:
		"""Stop all ongoing reconnection attempts"""
		for mac, event in self.reconnection_events.items():
			event.set()
		
		for mac, thread in self.reconnection_threads.items():
			if thread.is_alive():
				thread.join(timeout=2.0)
		
		self.reconnection_threads.clear()
		self.reconnection_events.clear()
		log_reconnection("All secondary reconnection attempts stopped")

# Initialize secondary reconnection manager
secondary_reconnection_manager = SecondaryReconnectionManager()

# ------------------------------
# DEVICE MANAGEMENT CLASS
# ------------------------------
class DeviceManager:
	def __init__(self, gtk_enabled: bool = False):
		self.device_volumes: Dict[str, str] = {}  # mac -> volume value
		self.gtk_enabled = gtk_enabled
		
	def get_device_volume(self, mac: str, default_volume: str) -> str:
		"""Get volume for specific device, with fallback to default"""
		with global_lock:
			return self.device_volumes.get(mac, default_volume)
	
	def set_device_volume(self, mac: str, volume: str) -> None:
		"""Set volume for specific device"""
		with global_lock:
			self.device_volumes[mac] = volume
			
	def get_connected_count(self) -> int:
		"""Get number of currently connected devices"""
		with global_lock:
			return len(connected_devices)
	
	def can_connect_more(self) -> bool:
		"""Check if we can connect more devices"""
		# Check if connection delay is active
		if connection_delay_manager.check_delay():
			remaining = connection_delay_manager.get_remaining_delay()
			log_delay(f"Connection delay active, {remaining:.1f}s remaining before allowing more connections")
			return False
			
		return self.get_connected_count() < MAX_DEVICES
	
	def is_device_connected(self, mac: str) -> bool:
		"""Check if device is already connected"""
		with global_lock:
			return mac in connected_devices
	
	def get_device_type(self, name: str) -> str:
		"""Determine device type based on name matching primary/secondary lists"""
		for primary_name in PRIMARY_DEVICES:
			if primary_name and primary_name in name:
				return "primary"
		
		for secondary_name in SECONDARY_DEVICES:
			if secondary_name and secondary_name in name:
				return "secondary"
				
		return "unknown"
	
	def add_connected_device(self, mac: str, name: str) -> None:
		"""Add device to connected devices list with type detection"""
		device_type = self.get_device_type(name)
		
		with global_lock:
			connected_devices[mac] = {
				'name': name,
				'volume': config["GATT"]["Volume"]["Value"],
				'last_seen': time.time(),
				'device_type': device_type,
			}
		
		# Clear connection in progress flags when connection succeeds
		if device_type == "primary":
			primary_connection_in_progress.clear()
		elif device_type == "secondary":
			secondary_connection_in_progress.clear()
			
		# Clear any reconnection attempts for this device
		if device_type == "secondary" and mac in secondary_reconnection_attempts:
			with global_lock:
				if mac in secondary_reconnection_attempts:
					del secondary_reconnection_attempts[mac]
		
		# Start connection delay if configured
		connection_delay_manager.start_delay(device_type, self)
		
		# Start audio combiner if both devices are connected and feature is enabled
		if (AUDIO_COMBINER_ENABLED and 
			self.get_connected_primary_count() >= 1 and 
			self.get_connected_secondary_count() >= 1 and
			not audio_combiner_started.is_set()):
			log_audio("Both devices connected, starting audio combiner")
			self.start_audio_combiner()
			
			# Start GTK UI if enabled
			if self.gtk_enabled and (AUDIO_GTK_UI_ENABLED or ENV_GTK_UI):
				log_gtk("Starting GTK UI for audio combiner (session-only mode)")
				start_gtk_ui()
	
	def remove_connected_device(self, mac: str, secondary_reconnect_enabled: bool = True) -> None:
		"""Remove device from connected devices list"""
		device_type = None
		device_name = None
		
		with global_lock:
			if mac in connected_devices:
				device_type = connected_devices[mac]['device_type']
				device_name = connected_devices[mac]['name']
				del connected_devices[mac]
		
		# Clear connection flags when device is removed
		if device_type == "primary":
			primary_connection_in_progress.clear()
		elif device_type == "secondary":
			secondary_connection_in_progress.clear()
			
			# Start reconnection attempt for secondary device if enabled
			if (secondary_reconnect_enabled and device_name and 
				not shutdown_evt.is_set() and self.can_connect_more()):
				log_reconnection(f"Secondary device {device_name} disconnected, starting reconnection process")
				secondary_reconnection_manager.start_reconnection_attempt(mac, device_name, self, secondary_reconnect_enabled)
		
		# Handle delay reset on device disconnect
		connection_delay_manager.handle_device_disconnect(device_type, self)
		
		# Stop audio combiner if we no longer have both devices
		if (AUDIO_COMBINER_ENABLED and 
			audio_combiner_started.is_set() and
			not (self.get_connected_primary_count() >= 1 and self.get_connected_secondary_count() >= 1)):
			log_audio("No longer have both devices, stopping audio combiner")
			self.stop_audio_combiner()
			
			# Stop GTK UI if running
			if self.gtk_enabled:
				log_gtk("Stopping GTK UI (audio combiner stopped)")
				stop_gtk_ui()
	
	def get_connected_devices_info(self) -> List[Tuple[str, str, str]]:
		"""Get list of connected devices as (mac, name, type) tuples"""
		with global_lock:
			return [(mac, data['name'], data['device_type']) for mac, data in connected_devices.items()]
	
	def update_device_seen(self, mac: str) -> None:
		"""Update last seen timestamp for device"""
		with global_lock:
			if mac in connected_devices:
				connected_devices[mac]['last_seen'] = time.time()
	
	def get_connected_primary_count(self) -> int:
		"""Get number of connected primary devices"""
		with global_lock:
			return sum(1 for data in connected_devices.values() if data['device_type'] == 'primary')
	
	def get_connected_secondary_count(self) -> int:
		"""Get number of connected secondary devices"""
		with global_lock:
			return sum(1 for data in connected_devices.values() if data['device_type'] == 'secondary')
	
	def is_primary_connected(self) -> bool:
		"""Check if ANY primary device is connected"""
		return self.get_connected_primary_count() > 0
	
	def is_secondary_connected(self) -> bool:
		"""Check if ANY secondary device is connected"""
		return self.get_connected_secondary_count() > 0
	
	def should_connect_device(self, device_type: str, mode_override: Optional[str] = None) -> bool:
		"""
		LEGACY-STYLE: Simple connection logic - instantly connect to any matching device
		unless we're at the device limit or the device type is excluded by mode.
		"""
		if not self.can_connect_more():
			return False
			
		# Check for mode overrides (PRIMARY_ONLY or SECONDARY_ONLY)
		if mode_override == "primary_only" and device_type != "primary":
			return False
		elif mode_override == "secondary_only" and device_type != "secondary":
			return False
			
		# LEGACY LOGIC: Simply check if we're not already connecting to this device type
		if device_type == "primary":
			return not primary_connection_in_progress.is_set()
		elif device_type == "secondary":
			return not secondary_connection_in_progress.is_set()
			
		return False

	def get_connection_status_summary(self) -> str:
		"""Get a summary of current connection status"""
		primary_count = self.get_connected_primary_count()
		secondary_count = self.get_connected_secondary_count()
		total_count = self.get_connected_count()
		
		# Build status parts conditionally
		status_parts = []
		status_parts.append(f"{primary_count}/1 primary")
		
		# Only include secondary if there are secondary devices configured
		if SECONDARY_DEVICES:
			status_parts.append(f"{secondary_count}/1 secondary")
		
		status_str = ", ".join(status_parts)
		
		# Add delay status if active
		if connection_delay_manager.check_delay():
			remaining = connection_delay_manager.get_remaining_delay()
			status_str += f" (delay: {remaining:.1f}s)"
			
		# Add audio combiner status
		if AUDIO_COMBINER_ENABLED:
			if audio_combiner_started.is_set():
				status_str += " [AUDIO COMBINED]"
				if self.gtk_enabled and (AUDIO_GTK_UI_ENABLED or ENV_GTK_UI):
					status_str += " [GTK UI - SESSION ONLY]"
			
		return f"{status_str} ({total_count}/{MAX_DEVICES} total)"
	
	def start_audio_combiner(self):
		"""Start the audio combiner"""
		global audio_combiner_thread
		if audio_combiner_thread is None or not audio_combiner_thread.is_alive():
			audio_combiner_stop.clear()
			audio_combiner_thread = threading.Thread(
				target=self._audio_combiner_worker,
				daemon=True
			)
			audio_combiner_thread.start()
	
	def stop_audio_combiner(self):
		"""Stop the audio combiner"""
		audio_combiner_stop.set()
		if audio_combiner_thread and audio_combiner_thread.is_alive():
			audio_combiner_thread.join(timeout=2.0)
		audio_combiner_started.clear()
	
	def _audio_combiner_worker(self):
		"""Worker thread for audio combiner"""
		try:
			audio_combiner = AudioCombinerManager(config["AudioCombiner"])
			if audio_combiner.start():
				# Keep the thread alive while audio combiner is running
				while not audio_combiner_stop.is_set():
					time.sleep(1)
				audio_combiner.stop()
		except Exception as e:
			log_error(f"Audio combiner worker error: {e}")
			audio_combiner_started.clear()

# Initialize device manager with GTK setting
gtk_enabled = AUDIO_GTK_UI_ENABLED or ENV_GTK_UI
device_manager = DeviceManager(gtk_enabled=gtk_enabled)

# ------------------------------
# ADVERTISEMENT MANAGEMENT
# ------------------------------
class Advertisement(dbus.service.Object):
	"""Manages a Bluetooth LE advertisement via DBus"""
	PATH_BASE = '/org/bluez/example/advertisement'

	def __init__(self, bus, index: int, ad_type: str, service_uuids: List[str],
				 local_name: str, includes: List[str]) -> None:
		self.path = self.PATH_BASE + str(index)
		self.bus = bus
		self.ad_type = ad_type
		self.service_uuids = service_uuids
		self.local_name = local_name
		self.includes = includes
		super().__init__(bus, self.path)

	def get_properties(self) -> dict:
		return {
			'org.bluez.LEAdvertisement1': {
				'Type': self.ad_type,
				'ServiceUUIDs': dbus.Array(self.service_uuids, signature='s'),
				'Includes': dbus.Array(self.includes, signature='s'),
				'LocalName': self.local_name,
				'LegacyAdvertising': dbus.Boolean(True)
			}
		}

	def get_path(self) -> dbus.ObjectPath:
		return dbus.ObjectPath(self.path)

	@dbus.service.method('org.bluez.LEAdvertisement1')
	def Release(self) -> None:
		log_info("Advertisement released")

# ------------------------------
# MAIN MANAGER CLASS
# ------------------------------
class BluetoothAshaManager:
	def __init__(self, args: argparse.Namespace) -> None:
		self.args = args
		self.ad_obj = None
		self.adv_loop = None
		self.adv_thread = None
		self.scan_thread: Optional[threading.Thread] = None
		self.gatt_triggered: bool = False
		self.timer: bool = False
		self.ad_registered: bool = False
		self.device_manager = device_manager
		
		# Determine secondary reconnection setting
		if hasattr(args, 'secondary_reconnect') and args.secondary_reconnect is not None:
			self.secondary_reconnect_enabled = args.secondary_reconnect
			log_info(f"Secondary reconnection {'enabled' if self.secondary_reconnect_enabled else 'disabled'} via command line", Fore.YELLOW)
		else:
			self.secondary_reconnect_enabled = SECONDARY_RECONNECTION_ENABLED
			log_info(f"Secondary reconnection {'enabled' if self.secondary_reconnect_enabled else 'disabled'} via config")
		
		# Set volume value based on arguments and environment variable
		env_volume = os.getenv("LND")
		if env_volume:
			self.volume_value = env_volume
			log_info(f"Using environment variable LND={env_volume} for volume (overrides config)", Fore.YELLOW)
		elif self.args.loudness:
			self.volume_value = config["GATT"]["Volume"]["Value"]
			log_info(f"Using configured volume value: {self.volume_value}", Fore.YELLOW)
		else:
			self.volume_value = config["GATT"]["Volume"]["Value"]
			log_info(f"Using configured volume value: {self.volume_value}")

		# Determine operation mode
		self.operation_mode = self._determine_operation_mode()
		
		# Connection delay command line override
		if hasattr(args, 'connection_delay') and args.connection_delay is not None:
			if args.connection_delay == 0:
				connection_delay_manager.delay_enabled = False
				log_info("Connection delay disabled via command line", Fore.YELLOW)
			else:
				connection_delay_manager.delay_enabled = True
				connection_delay_manager.delay_seconds = args.connection_delay
				log_info(f"Connection delay set to {args.connection_delay}s via command line", Fore.YELLOW)
		
		if hasattr(args, 'delay_only_after_both') and args.delay_only_after_both is not None:
			connection_delay_manager.only_after_both = args.delay_only_after_both
			log_info(f"Delay only after both: {args.delay_only_after_both}", Fore.YELLOW)
		
		# Audio combiner command line override
		if hasattr(args, 'audio_combiner') and args.audio_combiner is not None:
			global AUDIO_COMBINER_ENABLED
			AUDIO_COMBINER_ENABLED = args.audio_combiner
			log_info(f"Audio combiner {'enabled' if AUDIO_COMBINER_ENABLED else 'disabled'} via command line", Fore.MAGENTA)
		
		if hasattr(args, 'lat1') and args.lat1 is not None:
			global AUDIO_LAT1
			AUDIO_LAT1 = args.lat1
			log_info(f"Audio latency 1 set to {AUDIO_LAT1}ms via command line", Fore.MAGENTA)
		
		if hasattr(args, 'lat2') and args.lat2 is not None:
			global AUDIO_LAT2
			AUDIO_LAT2 = args.lat2
			log_info(f"Audio latency 2 set to {AUDIO_LAT2}ms via command line", Fore.MAGENTA)
		
		# GTK UI command line override
		if hasattr(args, 'gtk_ui') and args.gtk_ui is not None:
			global AUDIO_GTK_UI_ENABLED
			AUDIO_GTK_UI_ENABLED = args.gtk_ui
			log_info(f"GTK UI {'enabled' if AUDIO_GTK_UI_ENABLED else 'disabled'} via command line", Fore.CYAN)
		
		# Update device manager with new GTK setting
		device_manager.gtk_enabled = AUDIO_GTK_UI_ENABLED or ENV_GTK_UI
		
	def _determine_operation_mode(self) -> Optional[str]:
		"""Determine operation mode from environment variables and command line arguments"""
		env_primary_only = os.getenv("PRI_O")
		env_secondary_only = os.getenv("SEC_O")
		cli_primary_only = getattr(self.args, 'primary_only', False)
		cli_secondary_only = getattr(self.args, 'secondary_only', False)
		
		# Command line takes precedence over environment
		if cli_primary_only:
			log_info("PRIMARY ONLY mode enabled via command line", Fore.YELLOW)
			return "primary_only"
		elif cli_secondary_only:
			log_info("SECONDARY ONLY mode enabled via command line", Fore.YELLOW)
			return "secondary_only"
		elif env_primary_only and env_primary_only.lower() in ['1', 'true', 'yes']:
			log_info(f"PRIMARY ONLY mode enabled via environment variable PRIMARY_ONLY={env_primary_only}", Fore.YELLOW)
			return "primary_only"
		elif env_secondary_only and env_secondary_only.lower() in ['1', 'true', 'yes']:
			log_info(f"SECONDARY ONLY mode enabled via environment variable SECONDARY_ONLY={env_secondary_only}", Fore.YELLOW)
			return "secondary_only"
		
		log_info("Normal operation mode (both primary and secondary devices allowed)")
		return None

	# Bluetooth Initialization
	def initialize_bluetooth(self) -> None:
		"""Initialize Bluetooth by unblocking it, powering on, and setting up agents"""
		log_info("Initializing Bluetooth...", Fore.BLUE)
		run_command("rfkill unblock bluetooth")
		run_command("bluetoothctl power on")
		if self.args.pair:
			run_command("bluetoothctl discoverable on")
			run_command("bluetoothctl agent KeyboardDisplay")
		else:
			run_command("bluetoothctl agent on")
		run_command("bluetoothctl pairable on")

		while True:
			output = run_command("bluetoothctl show", capture_output=True, debug=False)
			if output and "Powered: yes" in output:
				break
			time.sleep(1)
		log_info("Bluetooth initialized", Fore.GREEN)

	def start_advertising(self, disable_advertisement: bool = False) -> None:
		"""Start Bluetooth LE advertising unless disabled"""
		if disable_advertisement:
			log_info("Advertisement disabled via CLI argument")
			return

		try:
			dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
			bus = dbus.SystemBus()
			adapter = bus.get_object('org.bluez', '/org/bluez/hci0')
			ad_manager = dbus.Interface(adapter, 'org.bluez.LEAdvertisingManager1')

			self.ad_obj = Advertisement(
				bus, 0, "peripheral",
				[GATT_ATTRIBUTE], "ASHA Stream", ["tx-power"]
			)

			def register_reply_handler() -> None:
				self.ad_registered = True
				log_info("Advertisement registered successfully", Fore.GREEN)

			def register_error_handler(e: Exception) -> None:
				self.ad_registered = False
				log_error(f"Failed to register advertisement: {e}")

			ad_manager.RegisterAdvertisement(
				self.ad_obj.get_path(), {},
				reply_handler=register_reply_handler,
				error_handler=register_error_handler
			)

			self.adv_loop = GLib.MainLoop()
			self.adv_thread = threading.Thread(target=self.adv_loop.run, daemon=True)
			self.adv_thread.start()

		except Exception as e:
			log_error(f"Advertising setup failed: {e}")
			if reconnect_evt.is_set():
				log_info("Reconnect triggered, restarting the script...")
				reconnect_evt.clear()
				self.cleanup()
				os.execv(sys.executable, [sys.executable] + sys.argv)

	def stop_advertising(self, disable_advertisement: bool = False) -> None:
		"""Stop active advertisement"""
		if disable_advertisement or not self.ad_obj:
			return
		try:
			bus = dbus.SystemBus()
			adapter = bus.get_object('org.bluez', '/org/bluez/hci0')
			ad_manager = dbus.Interface(adapter, 'org.bluez.LEAdvertisingManager1')
			ad_manager.UnregisterAdvertisement(self.ad_obj.get_path())
			try:
				self.ad_obj.remove_from_connection()
			except Exception as inner_error:
				log_warning(f"Failed to remove advertisement: {inner_error}")
			self.ad_obj = None
			if self.adv_loop:
				self.adv_loop.quit()
			if self.adv_thread:
				self.adv_thread.join(timeout=2)
		except Exception as e:
			log_warning(f"Error stopping advertisement: {e}")

	# Device Scanning and Connection
	def get_matching_devices(self) -> List[Tuple[str, str]]:
		"""Query bluetoothctl devices and filter based on device lists"""
		output = run_command("bluetoothctl devices", capture_output=True, debug=False) or ""
		matching_devices = []
		device_pattern = re.compile(r'^Device (([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}) (.*)$')
		
		for line in output.splitlines():
			match = device_pattern.match(line.strip())
			if match:
				mac, name = match.group(1), match.group(3)
				if any(bl in name for bl in BLACKLIST):
					continue
				
				# Check if device matches any of our primary or secondary devices
				for device_name in ALL_DEVICE_FILTERS:
					if device_name and device_name in name:
						matching_devices.append((mac, name))
						break
						
		return matching_devices

	def start_continuous_scan(self) -> None:
		"""Start continuous scan in a separate thread"""
		def scan_worker() -> None:
			new_pattern = re.compile(r'^\[NEW\] Device (([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}) (.*)$')
			chg_pattern = re.compile(r'^\[CHG\] Device (([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}) Name: (.*)$')
			while not shutdown_evt.is_set():
				try:
					proc = subprocess.Popen(
						["bluetoothctl"],
						stdin=subprocess.PIPE,
						stdout=subprocess.PIPE,
						stderr=subprocess.STDOUT,
						text=True
					)
					proc.stdin.write("scan on\n")
					proc.stdin.flush()
					while not shutdown_evt.is_set():
						line = proc.stdout.readline()
						if not line:
							continue
						line = line.strip()
						mac: Optional[str] = None
						name: Optional[str] = None

						new_match = new_pattern.match(line)
						if new_match:
							mac = new_match.group(1)
							name = new_match.group(3)
						else:
							chg_match = chg_pattern.match(line)
							if chg_match:
								mac = chg_match.group(1)
								name = chg_match.group(3)

						if mac and name:
							if not re.match(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$', mac):
								log_debug(f"Invalid MAC {mac} from line: {line}")
								continue
							
							# Check if device matches any of our device lists
							device_matches = False
							for device_name in ALL_DEVICE_FILTERS:
								if device_name and device_name in name:
									device_matches = True
									break
							
							if not device_matches:
								continue
								
							with global_lock:
								if mac not in processed_devices:
									processed_devices.add(mac)
									threading.Thread(
										target=self.handle_new_device,
										args=(mac, name),
										daemon=True
									).start()

					try:
						proc.stdin.write("scan off\n")
						proc.stdin.flush()
					except Exception:
						pass
					proc.terminate()
					proc.wait(timeout=2)
					break
				except Exception as e:
					if not shutdown_evt.is_set():
						log_error(f"Scan error: {e}")
					time.sleep(1)

		self.scan_thread = threading.Thread(target=scan_worker, daemon=True)
		self.scan_thread.start()

	async def async_connect_specific(self, mac_address: str, device_type: str) -> bool:
		"""Asynchronously attempt to connect to a given device up to three times"""
		# Set connection in progress flag
		if device_type == "primary":
			primary_connection_in_progress.set()
		elif device_type == "secondary":
			secondary_connection_in_progress.set()
		
		try:
			return await asyncio.wait_for(self._connect_attempt(mac_address, device_type), timeout=MAX_TIMEOUT)
		except asyncio.TimeoutError:
			run_remove_devices(mac_address)
			# Only trigger reset for primary device timeouts, not secondary
			if device_type == "primary" and self.args.reset_on_failure:
				log_warning("Connection to primary %s timed out — reset-on-failure triggered", mac_address)
				reset_evt.set()
				self.cleanup()
				os.execv(sys.executable, [sys.executable] + sys.argv)
			return False
		finally:
			# Clear connection in progress flag
			if device_type == "primary":
				primary_connection_in_progress.clear()
			elif device_type == "secondary":
				secondary_connection_in_progress.clear()

	async def _connect_attempt(self, mac_address: str, device_type: str) -> bool:
		if not re.match(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$', mac_address):
			log_debug(f"Invalid MAC address in connection attempt: {mac_address}")
			return False

		attempts = 0
		while not shutdown_evt.is_set() and attempts < 2:
			try:
				output = await asyncio.to_thread(
					run_command,
					f"bluetoothctl connect {mac_address}",
					capture_output=True
				)

				if output and any(s in output for s in ["Connection successful", "already connected"]):
					time.sleep(1)
					info = await asyncio.to_thread(
						run_command,
						f"bluetoothctl info {mac_address}",
						capture_output=True
					)
					if info and "Connected: yes" in info:
						return True

				log_warning(f"Connect attempt {attempts + 1} failed for {device_type}")

			except Exception as e:
				log_error(f"Connection attempt exception for {device_type}: {e}")
				# Only trigger reset for primary device exceptions, not secondary
				if device_type == "primary" and self.args.reset_on_failure and not shutdown_evt.is_set():
					log_warning("All connection attempts failed — restarting via os.execv()")
					reset_evt.set()
					try:
						self.cleanup()
					except Exception as e:
						log_error(f"Cleanup failed before restart: {e}")
					os.execv(sys.executable, [sys.executable] + sys.argv)

			attempts += 1
			await asyncio.sleep(DEFAULT_RETRY_INTERVAL)

		return False

	def handle_new_device(self, mac: str, name: str) -> None:
		"""LEGACY-STYLE: Process a newly discovered device - instantly connect to any matching device"""
		if any(black in name for black in BLACKLIST):
			log_info(f"Device {name} ({mac}) is blacklisted. Skipping connection.")
			return

		if not re.match(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$', mac):
			log_error(f"Invalid MAC address: {mac}")
			with global_lock:
				processed_devices.discard(mac)
			return

		# Determine device type
		device_type = self.device_manager.get_device_type(name)

		# LEGACY LOGIC: Check if we should connect based on simple rules
		if not self.device_manager.should_connect_device(device_type, self.operation_mode):
			log_debug(f"Skipping {device_type} device {name} - connection limit or mode restriction")
			return

		# Check if we can connect more devices (general limit)
		if not self.device_manager.can_connect_more():
			log_info(f"Maximum device limit ({MAX_DEVICES}) reached. Skipping {name}")
			with global_lock:
				processed_devices.discard(mac)
			return

		# Check if device is already connected
		if self.device_manager.is_device_connected(mac):
			log_debug(f"Device {name} ({mac}) is already connected")
			with global_lock:
				processed_devices.discard(mac)
			return

		log_device(f"New device detected: {name} ({mac})", device_type)
		
		# Check if connection delay is active
		if connection_delay_manager.check_delay():
			remaining = connection_delay_manager.get_remaining_delay()
			log_delay(f"Connection delay active, skipping {name} for {remaining:.1f}s")
			with global_lock:
				processed_devices.discard(mac)
			return
		
		# Use thread-safe async execution
		try:
			future = async_manager.run_coroutine_threadsafe(self.async_connect_specific(mac, device_type))
			success = future.result(timeout=MAX_TIMEOUT + 10)  # Add buffer for safety
		except Exception as e:
			log_error(f"Async connection failed: {e}")
			success = False

		if success:
			self.device_manager.add_connected_device(mac, name)
			run_pair_devices(mac)
			run_trust_background(mac)
			
			# Get the actual device type after adding (for logging)
			actual_device_type = self.device_manager.get_device_type(name)
			log_device(f"Connected to {name} ({mac})!", actual_device_type)
			
			# Immediately execute GATT operations for secondary devices after connection
			if actual_device_type == "secondary":
				log_gatt(f"Executing immediate GATT operations for secondary device {name}")
				# Use a small delay to ensure the connection is stable
				time.sleep(1)
				# Execute bluetoothctl connect to ensure proper GATT execution
				self.execute_secondary_gatt_operations(mac, name)
			
			# Start ASHA immediately when primary connects
			if actual_device_type == "primary" and self.operation_mode != "secondary_only":
				with global_lock:
					global asha_handle, asha_started
					if not asha_handle and not asha_started:
						log_asha("Primary device connected - starting ASHA sink")
						asha_handle = self.start_asha()
						asha_started = True
						threading.Thread(
							target=self.stream_asha_output,
							args=(asha_handle,),
							daemon=True
						).start()
			
			# Log connection summary
			status_summary = self.device_manager.get_connection_status_summary()
			log_connection(f"Connection status: {status_summary}", "success")
			
			run_trust_background(mac)
			disable_pairable_background()
			run_command("bluetoothctl discoverable off")
		else:
			# Only trigger reset for primary device failures, not secondary
			if device_type == "primary" and self.args.reset_on_failure:
				log_warning(f"Failed to connect to primary {mac} — reset-on-failure triggered")
				reset_evt.set()
				self.cleanup()
				os.execv(sys.executable, [sys.executable] + sys.argv)
			else:
				log_warning(f"Failed to connect to {device_type} device {name}")
				
			with global_lock:
				processed_devices.discard(mac)

	def execute_secondary_gatt_operations(self, mac: str, name: str) -> None:
		"""NEW: Execute bluetoothctl connect and GATT operations specifically for secondary devices"""
		try:
			log_gatt(f"Executing bluetoothctl connect for secondary device {name} to ensure GATT execution")
			
			# First, ensure the device is connected via bluetoothctl
			connect_output = run_command(f"bluetoothctl connect {mac}", capture_output=True)
			if connect_output and "Connection successful" in connect_output:
				# Small delay to ensure connection is stable
				time.sleep(0.5)
				
				# Now execute GATT operations with the secondary UUID
				log_gatt(f"Executing GATT operations for secondary device {name} with UUID {GATT_ATTRIBUTE_SEC}")
				
				process = subprocess.Popen(
					["bluetoothctl"],
					stdin=subprocess.PIPE,
					stdout=subprocess.PIPE,
					stderr=subprocess.PIPE,
					text=True
				)
				
				# Use the secondary UUID and volume value
				volume_value = config["GATT"]["Volume_Sec"]["Value"]
				commands = f"""connect {mac}
gatt.select-attribute {GATT_ATTRIBUTE_SEC}
gatt.write {volume_value}
exit
"""
				stdout, stderr = process.communicate(commands)
				if process.returncode == 0:
					log_gatt(f"Secondary GATT operations completed for {name} with volume {volume_value} and UUID {GATT_ATTRIBUTE_SEC}")
				else:
					log_error(f"Secondary GATT operations failed for {name}: {stderr.strip()}")
			else:
				log_warning(f"Failed to connect to secondary device {name} via bluetoothctl")
				
		except Exception as e:
			log_error(f"Error executing secondary GATT operations for {name}: {e}")

	# ASHA Sink Management
	def start_asha(self) -> Tuple[int, int]:
		"""
		Ensure the ASHA sink repository is available, build the executable if needed,
		then start it in a new process group with safety checks to prevent duplicates.
		"""
		# CRITICAL: Check for and kill any existing ASHA processes first
		with global_lock:
			if is_asha_process_running():
				log_warning("Existing ASHA process detected - terminating before start")
				kill_existing_asha_processes()
				time.sleep(1)
			
			# Double-check after cleanup
			if is_asha_process_running():
				log_error("ASHA processes still running after cleanup - aborting start")
				raise RuntimeError("Cannot start ASHA: existing processes still running")
			
			log_asha("Initializing ASHA sink...")
			
			if not os.path.isdir(CLONE_DIR):
				log_info("Cloning repository...")
				run_command(f"git clone {REPO_URL} {CLONE_DIR}")

			if not os.path.isfile(EXECUTABLE):
				log_info("Building ASHA sink...")
				os.makedirs(BUILD_DIR, exist_ok=True)
				run_command("cmake ..", cwd=BUILD_DIR)
				run_command("make", cwd=BUILD_DIR)

			try:
				# Check if cap_net_raw is already set
				result = subprocess.run(["getcap", EXECUTABLE], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
				
				if f"{EXECUTABLE} cap_net_raw=ep" not in result.stdout.strip():
					log_info("Setting cap_net_raw=ep on ASHA sink executable...")
					subprocess.run(["sudo", "/usr/sbin/setcap", "cap_net_raw=ep", EXECUTABLE], check=True)
				else:
					log_info("ASHA sink already has cap_net_raw=ep.")
					
			except subprocess.CalledProcessError as e:
				log_error(f"Failed to set/get capabilities: {e}")

			log_info("Starting ASHA sink...")
			
			# FINAL CHECK before starting
			if is_asha_process_running():
				log_error("ASHA process detected at final check - aborting")
				raise RuntimeError("ASHA process already running")
			
			master_fd, slave_fd = pty.openpty()
			try:
				proc = subprocess.Popen(
					["stdbuf", "-oL", EXECUTABLE, "--buffer_algorithm", "threaded", "--phy2m"],
					preexec_fn=os.setsid,
					stdin=slave_fd,
					stdout=slave_fd,
					stderr=slave_fd,
					close_fds=True
				)
				os.close(slave_fd)
				
				# Verify process started and is running
				time.sleep(0.5)
				if proc.poll() is not None:
					raise RuntimeError(f"ASHA process terminated immediately with code: {proc.returncode}")
				
				# Set the master_fd to non-blocking mode
				flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
				fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
				
				log_asha(f"ASHA sink started successfully (PID: {proc.pid})")
				return proc.pid, master_fd
				
			except Exception as e:
				log_error(f"ASHA startup failed: {e}")
				os.close(master_fd)
				# Ensure process is terminated if it started but then failed
				try:
					if 'proc' in locals():
						proc.terminate()
						proc.wait(timeout=2)
				except:
					pass
				raise

	def stream_asha_output(self, asha_handle: Tuple[int, int]) -> None:
		"""
		Reads the ASHA output and watches for connection drops or GATT triggers.
		"""
		child_pid, master_fd = asha_handle
		
		# Validate process is actually running
		try:
			os.kill(child_pid, 0)
		except ProcessLookupError:
			log_error("ASHA process not running at stream start")
			return
		
		buffer = b""
		last_stats: Optional[dict] = None
		
		buffer_x, buffer_y, buffer_z = [], [], []
		
		def safe_append(buf, val):
			if not isinstance(buf, list):
				buf = [buf] if isinstance(buf, (int, float)) else []
			buf.append(val)
			return buf

		def clr_history(buf, max_len=50):
			if not isinstance(buf, list):
				buf = [buf] if isinstance(buf, (int, float)) else []
				return False
			if len(buf) > max_len:
				buf[:] = buf[-max_len:]
				return True
			return False

		def mean_std(buf):
			if not isinstance(buf, (list, tuple)):
				buf = [buf]
			n = len(buf)
			if n == 0:
				return 0.0, 0.0
			mean_val = sum(buf) / n
			total = 0.0
			for v in buf:
				diff = v - mean_val
				total += diff * diff
			var = total / n
			x = var
			if x <= 0.0:
				return mean_val, 0.0
			approx = x
			for _ in range(8):
				approx = 0.5 * (approx + x / approx)
			std = approx
			return mean_val, std

		def detect_loss(x, y, z, max_history=50, tolerance=10.0, min_samples=10, drift_limit=0.10):
			if not isinstance(x, (list, tuple)):
				x = [x]
			if not isinstance(y, (list, tuple)):
				y = [y]
			if not isinstance(z, (list, tuple)):
				z = [z]

			clr_history(x, max_history)
			clr_history(y, max_history)
			clr_history(z, max_history)

			if len(x) < min_samples or len(y) < min_samples or len(z) < min_samples:
				return False

			mean_x, std_x = mean_std(x)
			mean_y, std_y = mean_std(y)
			mean_z, std_z = mean_std(z)

			last_vals = [x[-1], y[-1], z[-1]]
			means = [mean_x, mean_y, mean_z]
			stds = [std_x, std_y, std_z]

			z_scores = []
			for v, m, s in zip(last_vals, means, stds):
				diff = abs(v - m)
				z = 0.0 if s < 1e-6 else diff / s
				z_scores.append(z)

			def rate(buf):
				if not isinstance(buf, (list, tuple)) or len(buf) < 2:
					return 0.0
				return abs(buf[-1] - buf[-2])

			dx = rate(x)
			dy = rate(y)
			dz = rate(z)
			avg_rate = (dx + dy + dz) / 3.0

			# Ignore silent drift (no movement)
			if avg_rate < drift_limit:
				return False

			# Spike or sudden deviation = likely packet loss
			if all(zv > tolerance for zv in z_scores):
				return True

			return False

		# Updated regex to optionally capture Rssi: <val>, <val>
		ring_regex = re.compile(
			r"Ring Occupancy:\s*(\d+)\s+High:\s*(\d+)\s+Ring Dropped:\s*(\d+)\s+Total:\s*(\d+)\s+"
			r"Adapter Dropped:\s*(\d+)\s+Total:\s*(\d+)\s+Silence:\s*(\d+)\s+Total:\s*(\d+)"
			r"(?:\s+Rssi:\s*(\d+),\s*(\d+))?"
		)
		
		current_time = 0
		
		while not shutdown_evt.is_set():
			try:
				# Check if ASHA process is still alive
				try:
					os.kill(child_pid, 0)
				except ProcessLookupError:
					log_warning("ASHA process died unexpectedly")
					if self.args.reconnect:
						reconnect_evt.set()
					break
				
				rlist, _, _ = select.select([master_fd], [], [], 0.1)
				if master_fd in rlist:
					data = os.read(master_fd, 1024)
					if not data:
						break
					buffer += data
					while b"\n" in buffer:
						line, buffer = buffer.split(b"\n", 1)
						decoded = line.decode(errors="ignore")
						if "Ring Occupancy:" in decoded:
							match = ring_regex.search(decoded)
							if match:
								fields = [
									"Ring Occupancy",
									"High",
									"Ring Dropped",
									"Ring Total",
									"Adapter Dropped",
									"Adapter Total",
									"Silence",
									"Silence Total",
								]
								values = match.groups()

								current_stats = {field: int(val) for field, val in zip(fields, values[:8])}

								rssi_str = ""
								if values[8] is not None and values[9] is not None:
									rssi_str = f" Rssi: {values[8]}, {values[9]}"

								highlighted_parts = {}
								if last_stats is None:
									highlighted_parts = {field: str(current_stats[field]) for field in fields}
								else:
									for field in fields:
										if field == "Ring Occupancy":
											highlighted_parts[field] = str(current_stats[field])
										elif current_stats[field] != last_stats.get(field):
											highlighted_parts[field] = f"{Fore.YELLOW}{current_stats[field]}{Style.RESET_ALL}"
										else:
											highlighted_parts[field] = str(current_stats[field])

								highlighted_line = (
									f"Ring Occupancy: {highlighted_parts['Ring Occupancy']} "
									f"High: {highlighted_parts['High']} "
									f"Ring Dropped: {highlighted_parts['Ring Dropped']} "
									f"Total: {highlighted_parts['Ring Total']} "
									f"Adapter Dropped: {highlighted_parts['Adapter Dropped']} "
									f"Total: {highlighted_parts['Adapter Total']} "
									f"Silence: {highlighted_parts['Silence']} "
									f"Total: {highlighted_parts['Silence Total']}"
									f"{rssi_str}"
								)

								log_debug(f"[ASHA] {highlighted_line}")
								last_stats = current_stats
								
								if config["GATT"]["Detect_loss"]:
									buffer_x = safe_append(buffer_x, current_stats['Ring Dropped'])
									buffer_y = safe_append(buffer_y, current_stats['Adapter Dropped'])
									buffer_z = safe_append(buffer_z, current_stats['Silence'])

									if detect_loss(buffer_x, buffer_y, buffer_z):
										log_warning("ASHA packet loss detected (auto reconnect)")
										if self.args.reconnect:
											# Remove all connected devices on ASHA failure
											connected_devices_info = self.device_manager.get_connected_devices_info()
											for mac, name, _ in connected_devices_info:
												self.device_manager.remove_connected_device(mac, self.secondary_reconnect_enabled)
											reconnect_evt.set()
											asha_restart_evt.set()
								
							else:
								log_debug(f"[ASHA] {decoded}")
						else:
							log_debug(f"[ASHA] {decoded}")

						if any(phrase in decoded for phrase in [
							"Connected: false",
							"Assertion !m_sock' failed.",
							"GDBus.Error:org.bluez.Error.InProgress: In Progress",
							"GDBus.Error:org.freedesktop.DBus.Error.NoReply: Remote peer disconnected",
							"Timeout was reached",
							"GDBus.Error:org.bluez.Error.Failed: Not connected",
							"Removing Sink",
						]):
							log_warning("ASHA connection dropped")
							self.gatt_triggered = False
								
							if self.args.reconnect:
								# Remove all connected devices on ASHA failure
								connected_devices_info = self.device_manager.get_connected_devices_info()
								for mac, name, _ in connected_devices_info:
									self.device_manager.remove_connected_device(mac, self.secondary_reconnect_enabled)
								reconnect_evt.set()
								asha_restart_evt.set()
							return

						if any(phrase in decoded for phrase in [
							"Connection Ready Callback Set"
						]):
							current_time = time.perf_counter()
							log_debug(f"Countdown started {current_time}")
							self.timer = True
						
						if current_time >= Timeout_qs:
							log_warning("ASHA connection dropped (timeout)")
							self.timer = False
							self.gatt_triggered = False
							current_time = 0
							if self.args.reconnect:
								connected_devices_info = self.device_manager.get_connected_devices_info()
								for mac, name, _ in connected_devices_info:
									self.device_manager.remove_connected_device(mac, self.secondary_reconnect_enabled)
								reconnect_evt.set()
								asha_restart_evt.set()
							return
							
						if any(phrase in decoded for phrase in [
							"Properties read callback"
						]):
							log_debug(f"Countdown stopped {current_time}")
							self.timer = False
							current_time = 0
							
						if ("on_change_state" in decoded and
								("new: PAUSED" in decoded or "new: STREAMING" in decoded) and
								not self.gatt_triggered and not self.args.clean_state):
							self.gatt_triggered = True
							log_info("Detected audio state change")
							current_time = 0
							# Perform GATT operations on all connected devices
							connected_devices_info = self.device_manager.get_connected_devices_info()
							for mac, name, device_type in connected_devices_info:
								if config["GATT"]["Allow"] == True:
									log_gatt(f"Triggering GATT operations on {name}...")
									mode_config = config["GATT"]["Trigger"]
									mode: str = mode_config.get("Modes", "increment") if isinstance(mode_config, dict) else "increment"
									duration: float = mode_config.get("Duration_s", 0.3) if isinstance(mode_config, dict) else 0.3
									if duration < 0.2:
										log_warning("first trigger may fail")
									frequency: int = config["GATT"].get("Frequency_int", 3)
									
									if mode == "burst":
										for _ in range(frequency):
											time.sleep(duration)
											self.perform_gatt_operations(mac, name, device_type)
									elif mode == "increment":
										for i in range(1, frequency + 1):
											delay = duration * i
											time.sleep(delay)
											self.perform_gatt_operations(mac, name, device_type)
									else:
										for _ in range(frequency):
											time.sleep(duration)
											self.perform_gatt_operations(mac, name, device_type)

			except Exception as e:
				if not shutdown_evt.is_set():
					log_error(f"ASHA stream error: {e}")
					reset_evt.set()
				break

	def perform_gatt_operations(self, mac_address: str, device_name: str, device_type: str) -> bool:
		"""Perform GATT operations by connecting to the device"""
		# Get device-specific volume or use default
		volume_value = self.device_manager.get_device_volume(mac_address, self.volume_value)
		
		# Use different UUID for secondary devices
		if device_type == "secondary":
			gatt_uuid = GATT_ATTRIBUTE_SEC
			log_gatt(f"Using secondary UUID for {device_name}: {gatt_uuid}")
		else:
			gatt_uuid = GATT_ATTRIBUTE
		
		log_gatt(f"Starting GATT operations for {device_name} with volume value: {volume_value}, UUID: {gatt_uuid}")
		try:
			process = subprocess.Popen(
				["bluetoothctl"],
				stdin=subprocess.PIPE,
				stdout=subprocess.PIPE,
				stderr=subprocess.PIPE,
				text=True
			)
			commands = f"""connect {mac_address}
gatt.select-attribute {gatt_uuid}
gatt.write {volume_value}
exit
"""
			stdout, stderr = process.communicate(commands)
			if process.returncode == 0:
				log_gatt(f"GATT operations completed with volume {volume_value} and UUID {gatt_uuid}")
				return True
			else:
				log_error(f"GATT operations failed: {stderr.strip()}")
				return False
		except Exception as e:
			log_error(f"GATT exception: {e}")
			return False

	def monitor_device_changes(self) -> None:
		"""Periodically monitor the list of connected devices"""
		while not shutdown_evt.is_set():
			try:
				# Get current connected devices from our tracking
				current_connected = set([mac for mac, _, _ in self.device_manager.get_connected_devices_info()])
				
				# Get actual connected devices from bluetoothctl
				output = run_command("bluetoothctl devices", capture_output=True, debug=False) or ""
				actual_connected: Set[str] = set()
				for line in output.splitlines():
					if "Device" in line:
						parts = line.strip().split()
						if len(parts) >= 2:
							actual_connected.add(parts[1])
				
				# Check for missing devices
				missing = current_connected - actual_connected
				
				if missing:
					log_warning(f"Missing connections: {', '.join(missing)}")
					for mac in missing:
						self.device_manager.remove_connected_device(mac, self.secondary_reconnect_enabled)
					
					# Use the new summary method
					status_summary = self.device_manager.get_connection_status_summary()
					log_connection(f"Remaining: {status_summary}", "warning")
					
					# Only trigger full reconnect for primary devices, not secondary
					# Secondary devices are handled by the reconnection manager
					has_primary_missing = any(
						connected_devices.get(mac, {}).get('device_type') == 'primary' 
						for mac in missing
					)
					if has_primary_missing:
						reconnect_evt.set()
					
				time.sleep(0.2)
			except Exception as e:
				log_error(f"Monitor error: {e}")
				time.sleep(2)

	def terminate_asha(self) -> None:
		"""Gracefully terminate the ASHA sink process with comprehensive cleanup"""
		with global_lock:
			global asha_handle, asha_started
			if asha_handle:
				child_pid, master_fd = asha_handle
				log_info(f"Terminating ASHA process (PID: {child_pid})...")
				
				try:
					# Try graceful termination first
					pgid = os.getpgid(child_pid)
					os.killpg(pgid, signal.SIGTERM)
					
					# Wait for graceful shutdown
					timeout = 1
					end_time = time.time() + timeout
					terminated = False
					
					while time.time() < end_time:
						try:
							# Check if process still exists
							os.kill(child_pid, 0)
							time.sleep(0.1)
						except ProcessLookupError:
							terminated = True
							break
					
					if not terminated:
						log_warning("ASHA process did not terminate gracefully - forcing kill")
						try:
							os.killpg(pgid, signal.SIGKILL)
							time.sleep(0.5)
						except ProcessLookupError:
							pass  # Process already gone
							
				except ProcessLookupError:
					log_info("ASHA process already terminated")
				except Exception as e:
					log_error(f"Error during ASHA termination: {e}")
					# Final attempt - kill any remaining ASHA processes
					kill_existing_asha_processes()
				finally:
					try:
						os.close(master_fd)
					except Exception:
						pass
					asha_handle = None
					asha_started = False
					
				log_asha("ASHA sink terminated")
			else:
				# If handle is None but processes might exist, clean them up
				if is_asha_process_running():
					log_warning("Cleaning up orphaned ASHA processes")
					kill_existing_asha_processes()

	def cleanup(self) -> None:
		"""Cleanup routine for shutting down all components gracefully"""
		log_info("Cleaning up...", Fore.BLUE)
		self.stop_advertising(self.args.disable_advertisement)
		
		# Stop all secondary reconnection attempts
		secondary_reconnection_manager.stop_all_reconnections()
		
		# Reset any active connection delay
		connection_delay_manager.reset_delay()
		
		# Stop GTK UI if running
		if device_manager.gtk_enabled:
			stop_gtk_ui()
		
		# Stop audio combiner if running
		if audio_combiner_started.is_set():
			device_manager.stop_audio_combiner()
		
		if self.args.disconnect:
			run_command("bluetoothctl agent off", check=False)
			run_command("bluetoothctl power off", check=False)
		
		with global_lock:
			global asha_handle
			if asha_handle:
				self.terminate_asha()
		
		run_command("bluetoothctl pairable off", check=False)
		shutdown_evt.set()
		async_manager.stop()
		log_info("Cleanup complete", Fore.GREEN)

	def signal_handler(self, sig, frame) -> None:
		"""Handle signals for graceful shutdown"""
		log_warning(f"Received signal {sig}, shutting down...")
		self.cleanup()
		sys.exit(0)

	# Main loop
	def run(self) -> None:
		"""Main loop to initialize Bluetooth, start scanning, monitor devices, and manage the ASHA sink"""
		signal.signal(signal.SIGINT, self.signal_handler)
		signal.signal(signal.SIGTERM, self.signal_handler)
		signal.signal(signal.SIGHUP, self.signal_handler)
		
		# Start async event loop
		async_manager.start()
		
		try:
			self.initialize_bluetooth()
			self.start_advertising(self.args.disable_advertisement)
			self.start_continuous_scan()
			threading.Thread(target=self.monitor_device_changes, daemon=True).start()

			while not shutdown_evt.is_set():
				# Get all matching devices
				matching_devices = self.get_matching_devices()
				
				if matching_devices:
					with global_lock:
						current_macs = {mac for mac, _ in matching_devices}
						new_macs = current_macs - processed_devices
						for mac in new_macs:
							# Check if we can connect more devices
							if not self.device_manager.can_connect_more():
								log_info(f"Maximum device limit ({MAX_DEVICES}) reached, skipping new devices")
								break
								
							name = next((n for m, n in matching_devices if m == mac), "Unknown")
							processed_devices.add(mac)
							threading.Thread(
								target=self.handle_new_device,
								args=(mac, name),
								daemon=True
							).start()

				# Manage ASHA sink restart
				if asha_restart_evt.is_set():
					log_info("ASHA restart triggered")
					self.terminate_asha()
					
					# Wait a bit to ensure clean state
					time.sleep(1)
					
					# Final check before restart
					with global_lock:
						global asha_handle, asha_started
						if is_asha_process_running():
							log_error("ASHA processes still running after termination - skipping restart")
							asha_restart_evt.clear()
						else:
							# Only restart if we have a primary device connected
							# Skip in SECONDARY_ONLY mode
							if (self.device_manager.is_primary_connected() and 
								self.operation_mode != "secondary_only"):
								try:
									asha_handle = self.start_asha()
									asha_started = True
									asha_restart_evt.clear()
									threading.Thread(
										target=self.stream_asha_output,
										args=(asha_handle,),
										daemon=True
									).start()
								except Exception as e:
									log_error(f"Failed to restart ASHA: {e}")
									asha_restart_evt.clear()
							else:
								log_info("No primary connected - skipping ASHA restart")
								asha_restart_evt.clear()

				if reset_evt.is_set():
					log_info("Controller resetting...")
					reset_evt.clear()
					self.cleanup()
					os.execv(sys.executable, [sys.executable] + sys.argv)

				if reconnect_evt.is_set():
					log_info("Reconnect triggered, restarting the script...")
					reconnect_evt.clear()
					self.cleanup()
					os.execv(sys.executable, [sys.executable] + sys.argv)

				time.sleep(1)
		except Exception as e:
			log_error(f"Fatal error: {e}")
		finally:
			self.cleanup()

# ------------------------------
# ENTRY POINT
# ------------------------------
def main() -> None:
	global MAX_DEVICES, PRIORITY_PRIMARY
	
	parser = argparse.ArgumentParser(description="Bluetooth ASHA Manager with Audio Sink Combining")
	parser.add_argument('-c', '--clean-state', action='store_true',
						help='Skip automatic GATT operations on state change')
	parser.add_argument('-r', '--reconnect', action='store_true',
						help='Enable automatic ASHA restart if device disconnects')
	parser.add_argument('-d', '--disconnect', action='store_true',
						help='Disconnect Bluetooth devices on exit')
	parser.add_argument('-p', '--pair', action='store_true',
						help='Enable persistent pairing mode')
	parser.add_argument('-da', '--disable-advertisement', action='store_true',
						help='Disable Bluetooth LE advertising')
	parser.add_argument('-rof','--reset-on-failure', action='store_true', 
						help='Auto-reset adapter on ASHA connect failure')
	parser.add_argument('-l', '--loudness', action='store_true',
						help="Override configured GATT Trigger. It ranged from 0x80 to 0xFF.\nFF may not work on some devices try 0xF0 instead.\nDo allow env can be set as LND= appended into the command line for ease of access")
	parser.add_argument('-md', '--max-devices', type=int, default=None,
						help=f"Maximum number of devices to connect simultaneously (default: {MAX_DEVICES})")
	parser.add_argument('-pp', '--priority-primary', action='store_true', default=None,
						help="Prioritize primary devices over secondary (default: from config)")
	parser.add_argument('-po','--primary-only', action='store_true',
						help="Only connect to primary devices (overrides config and environment(PRI_O))")
	parser.add_argument('-so','--secondary-only', action='store_true',
						help="Only connect to secondary devices (overrides config and environment(SEC_O))")
	
	# Secondary reconnection argument
	parser.add_argument('-sr', '--secondary-reconnect', action='store_true', default=None,
						help='Enable background reconnection for secondary devices without restarting Bluetooth (overrides config)')
	parser.add_argument('-nsr', '--no-secondary-reconnect', action='store_false', dest='secondary_reconnect',
						help='Disable background reconnection for secondary devices (overrides config)')
	
	# Connection delay arguments
	parser.add_argument('-cd', '--connection-delay', type=float, default=None,
						help='Connection delay in seconds after device connects (0 to disable, overrides config)')
	parser.add_argument('-dob', '--delay-only-after-both', action='store_true', default=None,
						help='Only apply connection delay after both primary and secondary are connected')
	
	# Audio combiner arguments
	parser.add_argument('-ac', '--audio-combiner', action='store_true', default=None,
						help='Enable audio sink combiner for ASHA and BT devices (overrides config)')
	parser.add_argument('-nac', '--no-audio-combiner', action='store_false', dest='audio_combiner',
						help='Disable audio sink combiner (overrides config)')
	parser.add_argument('-lat1', '--lat1', type=int, default=None,
						help='Audio latency for ASHA sink in milliseconds (overrides config)')
	parser.add_argument('-lat2', '--lat2', type=int, default=None,
						help='Audio latency for BT sink in milliseconds (overrides config)')
	
	# GTK UI arguments
	parser.add_argument('-gtk', '--gtk-ui', action='store_true', default=None,
						help='Enable GTK UI for adjusting audio latencies (overrides config)')
	parser.add_argument('-ngtk', '--no-gtk-ui', action='store_false', dest='gtk_ui',
						help='Disable GTK UI (overrides config)')
	
	args = parser.parse_args()

	if args.max_devices is not None:
		MAX_DEVICES = args.max_devices
		log_info(f"Maximum devices set to: {MAX_DEVICES}")

	if args.priority_primary is not None:
		PRIORITY_PRIMARY = args.priority_primary
		log_info(f"Primary priority set to: {PRIORITY_PRIMARY}")

	manager = BluetoothAshaManager(args)
	manager.run()

if __name__ == "__main__":
	main()
