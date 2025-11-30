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
#!/usr/bin/env python3

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

# GATT Configuration - NEW: Separate UUID for secondary devices
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

# Connection state tracking (thread-safe by design)
primary_connection_in_progress = threading.Event()
secondary_connection_in_progress = threading.Event()

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
# PROCESS MANAGEMENT UTILITIES
# ------------------------------
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
# DEVICE MANAGEMENT CLASS
# ------------------------------
class DeviceManager:
	def __init__(self):
		self.device_volumes: Dict[str, str] = {}  # mac -> volume value
		
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
	
	def remove_connected_device(self, mac: str) -> None:
		"""Remove device from connected devices list"""
		device_type = None
		with global_lock:
			if mac in connected_devices:
				device_type = connected_devices[mac]['device_type']
				del connected_devices[mac]
		
		# Clear connection flags when device is removed
		if device_type == "primary":
			primary_connection_in_progress.clear()
		elif device_type == "secondary":
			secondary_connection_in_progress.clear()
	
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
		Simple connection logic
		"""
		if not self.can_connect_more():
			return False
			
		# Check for mode overrides (PRIMARY_ONLY or SECONDARY_ONLY)
		if mode_override == "primary_only" and device_type != "primary":
			return False
		elif mode_override == "secondary_only" and device_type != "secondary":
			return False
			
		# Simply check if we're not already connecting to this device type
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
		return f"{status_str} ({total_count}/{MAX_DEVICES} total)"

# Initialize device manager
device_manager = DeviceManager()

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
		""" Process a newly discovered device """
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

		# Check if we should connect based on simple rules
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
			
			# NEW: Immediately execute GATT operations for secondary devices after connection
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
												self.device_manager.remove_connected_device(mac)
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
									self.device_manager.remove_connected_device(mac)
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
									self.device_manager.remove_connected_device(mac)
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
		
		# NEW: Use different UUID for secondary devices
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
						self.device_manager.remove_connected_device(mac)
					
					# Use the new summary method
					status_summary = self.device_manager.get_connection_status_summary()
					log_connection(f"Remaining: {status_summary}", "warning")
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
	
	parser = argparse.ArgumentParser(description="Bluetooth ASHA Manager")
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

