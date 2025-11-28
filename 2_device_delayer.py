#!/usr/bin/env python3
import os
import sys
import subprocess
import time
import signal
import argparse
import threading
import re

# === CONFIG ===
SINK1 = "sink_asha"
SINK2 = "sink_bt"
COMB = "sink_combined"
DESC1 = "ASHA_Sink"
DESC2 = "BT_Sink"
DESC3 = "Combined_Sink"

# Do use "pactl list short sources" in your pipewire machine to find out the name should be different across the devices
TARGET1 = os.environ.get('ASHA_SINK', 'asha_16450405641617933895') # Please change this to your asha 
TARGET2 = os.environ.get('BT_SINK', 'bluez_output.#x#x#X#') # Please change this as well 

'''
WARNING!
DO NOT USE EASYEFFECT WITH THIS IT WILL BREAK
I will try to make it better
'''

# === PARSE ARGS ===
parser = argparse.ArgumentParser(description='Combine ASHA and BT PulseAudio sinks')
parser.add_argument('chan1', nargs='?', default='both', choices=['left', 'right', 'both'])
parser.add_argument('chan2', nargs='?', default='both', choices=['left', 'right', 'both'])
parser.add_argument('-r', '--reconnect', action='store_true', help='Attempt to reconnect BT device on disconnect')
args = parser.parse_args()

CHAN1 = args.chan1
CHAN2 = args.chan2
LAT1 = float(os.environ.get('ASHA_LAT', '120')) # adjust to any latency you wanted, mine is  MEDEL G722 audiostream adapter paired up with Phonak hearing aid so i have to put 120ms delay for the audio stream adapter to stay sync
LAT2 = float(os.environ.get('BT_LAT', '0'))

# === GLOBALS ===
VOL1_ORIG = VOL2_ORIG = None
ID1 = ID2 = LB1 = LB2 = ID_COMB = None
stop_flag = threading.Event()

# === HELPERS ===
def run_cmd(cmd, capture=False, check=True):
    if capture:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip()
    else:
        subprocess.check_call(cmd)

def get_map(channel):
    if channel == 'left': return 'channel_map=front-left,front-left'
    if channel == 'right': return 'channel_map=front-right,front-right'
    if channel == 'both': return ''
    print(f"[FATAL] Invalid channel: {channel}", file=sys.stderr)
    sys.exit(1)


def wait_sink(name):
    print(f"[*] Waiting indefinitely for sink: {name}")

    # First check immediately in case it already exists
    out = run_cmd(['pactl', 'list', 'short', 'sinks'], capture=True)
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == name:
            print(f"[✓] Sink already present: {name}")
            return

    # True event-based wait
    sub = subprocess.Popen(
        ['pactl', 'subscribe'],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1
    )

    try:
        for line in sub.stdout:
            if "Event 'new' on sink" in line or "Event 'change' on sink" in line:
                out = run_cmd(['pactl', 'list', 'short', 'sinks'], capture=True)
                for s in out.splitlines():
                    parts = s.split()
                    if len(parts) >= 2 and parts[1] == name:
                        print(f"[✓] Sink detected via event: {name}")
                        return
    except KeyboardInterrupt:
        print("\n[!] Interrupted while waiting for sink.")
        sys.exit(0)
    finally:
        try:
            sub.kill()
        except:
            pass


def create_null_sink(name, desc):
    return run_cmd([
        'pactl', 'load-module', 'module-null-sink',
        f'sink_name={name}', f'sink_properties=device.description={desc}'
    ], capture=True)

# Updated create_loopback: duplicates working channel to broken one
def create_loopback(source_sink, target_sink, channel, latency):
    if target_sink == TARGET2:
        if channel == 'left':
            # RIGHT → LEFT
            cmd = [
                'pactl', 'load-module', 'module-loopback',
                f'source={source_sink}.monitor',
                f'sink={target_sink}',
                'channels=2',
                'remix=no',
                'channel_map=front-right,front-right',
                f'latency_msec={latency}',
                'volume=0x10000'
            ]
        elif channel == 'right':
            # LEFT → RIGHT
            cmd = [
                'pactl', 'load-module', 'module-loopback',
                f'source={source_sink}.monitor',
                f'sink={target_sink}',
                'channels=2',
                'remix=no',
                'channel_map=front-left,front-left',
                f'latency_msec={latency}',
                'volume=0x10000'
            ]
        else:
            # both healthy
            cmd = [
                'pactl', 'load-module', 'module-loopback',
                f'source={source_sink}.monitor',
                f'sink={target_sink}',
                'channels=2',
                'remix=yes',
                f'latency_msec={latency}',
                'volume=0x10000'
            ]
    else:
        # ASHA or other sinks
        mapping = get_map(channel)
        cmd = [
            'pactl', 'load-module', 'module-loopback',
            f'source={source_sink}.monitor',
            f'sink={target_sink}',
            f'latency_msec={latency}',
            'volume=0x10000'
        ]
        if mapping:
            cmd.append(mapping)

    return run_cmd(cmd, capture=True)

def get_vol(name):
    out = run_cmd(['pactl', 'get-sink-volume', name], capture=True)
    for line in out.splitlines():
        if 'Volume:' in line:
            return line.split()[4]
    return None

def set_vol(name, vol):
    run_cmd(['pactl', 'set-sink-volume', name, vol])

def extract_mac_from_sink(sink_name):
    match = re.search(r'bluez_output\.([0-9A-Fa-f_]+)\.\d+', sink_name)
    if not match: return None
    return match.group(1).replace('_', ':')

def try_reconnect_bt():
    mac = extract_mac_from_sink(TARGET2)
    if not mac:
        print("[WARN] Could not extract MAC address from BT sink name.", file=sys.stderr)
        return
    print(f"[RECONNECT] Attempting to reconnect to {mac}...")
    try:
        subprocess.run(['bluetoothctl', 'connect', mac], check=True)
        print("[RECONNECT] Reconnection command sent.")
    except subprocess.CalledProcessError:
        print("[ERROR] Failed to reconnect using bluetoothctl", file=sys.stderr)

def cleanup():
    print("[*] Cleaning up...")
    for mod in (LB1, LB2, ID_COMB, ID1, ID2):
        try:
            run_cmd(['pactl', 'unload-module', mod], check=False)
        except:
            pass
    for target, vol in ((TARGET1, VOL1_ORIG), (TARGET2, VOL2_ORIG)):
        try:
            set_vol(target, vol)
        except:
            print(f"[WARN] Could not restore volume for {target}", file=sys.stderr)
    try:
        run_cmd(['pactl', 'set-default-sink', TARGET1], check=False)
    except:
        print("[WARN] Failed to restore default sink", file=sys.stderr)
    print("[✓] Cleanup complete.")

def monitor_sinks():
    """
    Fully dynamic monitor for ASHA + BT sinks.
    - Handles disconnect/reconnect of ASHA and BT
    - Reapplies loopbacks and updates combined sink slaves
    - Event-driven; no polling
    """
    global LB1, LB2, ID_COMB

    sub = subprocess.Popen(['pactl', 'subscribe'],
                           stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL,
                           text=True,
                           bufsize=1)

    try:
        for line in sub.stdout:
            if stop_flag.is_set():
                break
            decoded = line.strip()

            # --------------------
            # ASHA removal
            # --------------------
            if "Event 'remove' on sink" in decoded and TARGET1 in decoded:
                print(f"[!] ASHA sink {TARGET1} removed! Waiting for it...")
                LB1 = None

                # Wait for ASHA to reappear
                wait_sink(TARGET1)
                print(f"[✓] ASHA sink {TARGET1} reappeared!")

                # Reapply loopback
                LB1 = create_loopback(SINK1, TARGET1, CHAN1, LAT1)
                print(f"[*] ASHA loopback reapplied to {TARGET1}")

                # Update combined sink slaves
                slaves = [SINK1]
                out = run_cmd(['pactl', 'list', 'short', 'sinks'], capture=True)
                if any(line.split()[1] == TARGET2 for line in out.splitlines()) and LB2:
                    slaves.append(SINK2)
                run_cmd(['pactl', 'set-sink-slaves', COMB, ','.join(slaves)])
                print(f"[✓] Combined sink {COMB} updated after ASHA reconnect")

            # --------------------
            # BT removal
            # --------------------
            elif "Event 'remove' on sink" in decoded and TARGET2 in decoded:
                print(f"[!] BT sink {TARGET2} removed!")
                if args.reconnect:
                    try_reconnect_bt()
                if LB2:
                    try:
                        run_cmd(['pactl', 'unload-module', LB2], check=False)
                        LB2 = None
                    except:
                        pass

                # Update combined sink slaves to remove BT
                run_cmd(['pactl', 'set-sink-slaves', COMB, SINK1])
                print(f"[✓] Combined sink {COMB} updated after BT removal")

            # --------------------
            # New/changed sink (BT or ASHA reappearance)
            # --------------------
            elif "Event 'new' on sink" in decoded or "Event 'change' on sink" in decoded:
                out = run_cmd(['pactl', 'list', 'short', 'sinks'], capture=True)

                # BT appeared
                if any(line.split()[1] == TARGET2 for line in out.splitlines()) and not LB2:
                    print(f"[✓] BT sink {TARGET2} appeared!")
                    LB2 = create_loopback(SINK2, TARGET2, CHAN2, LAT2)
                    print(f"[*] BT loopback applied to {TARGET2}")

                    # Add BT to combined sink
                    slaves = [SINK1, SINK2]
                    run_cmd(['pactl', 'set-sink-slaves', COMB, ','.join(slaves)])
                    print(f"[✓] BT sink {TARGET2} added to combined sink {COMB}")

                # ASHA appeared (if somehow LB1 is missing)
                if any(line.split()[1] == TARGET1 for line in out.splitlines()) and not LB1:
                    print(f"[✓] ASHA sink {TARGET1} appeared unexpectedly!")
                    LB1 = create_loopback(SINK1, TARGET1, CHAN1, LAT1)
                    print(f"[*] ASHA loopback reapplied to {TARGET1}")

                    # Ensure combined sink includes ASHA (and BT if exists)
                    slaves = [SINK1]
                    if any(line.split()[1] == TARGET2 for line in out.splitlines()) and LB2:
                        slaves.append(SINK2)
                    run_cmd(['pactl', 'set-sink-slaves', COMB, ','.join(slaves)])
                    print(f"[✓] Combined sink {COMB} updated after ASHA addition")

    except KeyboardInterrupt:
        pass
    finally:
        try:
            sub.kill()
        except:
            pass


def main():
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    try:
        print("[*] Waiting for sinks...")
        wait_sink(TARGET1)
        wait_sink(TARGET2)

        global VOL1_ORIG, VOL2_ORIG
        VOL1_ORIG = get_vol(TARGET1)
        VOL2_ORIG = get_vol(TARGET2)

        print("[*] Creating null sinks...")
        global ID1, ID2
        ID1 = create_null_sink(SINK1, DESC1)
        ID2 = create_null_sink(SINK2, DESC2)

        print("[*] Creating loopbacks...")
        global LB1, LB2
        LB1 = create_loopback(SINK1, TARGET1, CHAN1, LAT1)
        LB2 = create_loopback(SINK2, TARGET2, CHAN2, LAT2)

        print("[*] Creating combined sink...")
        global ID_COMB
        ID_COMB = run_cmd([
            'pactl', 'load-module', 'module-combine-sink',
            f'sink_name={COMB}', f'slaves={SINK1},{SINK2}',
            f'sink_properties=device.description={DESC3}'
        ], capture=True)

        wait_sink(COMB)
        run_cmd(['pactl', 'set-default-sink', COMB])
        set_vol(COMB, VOL1_ORIG)

        print(f"[+] Default sink set to {COMB}")
        for s in (TARGET1, TARGET2, SINK1, SINK2):
            try:
                run_cmd(['pactl', 'set-sink-volume', s, '100%'], check=False)
            except:
                print(f"[WARN] Could not set volume on {s}")

        print("[✓] Combined sink ready.")
        print(f"    • {SINK1} → {TARGET1} (chan={CHAN1}, lat={LAT1}ms)")
        print(f"    • {SINK2} → {TARGET2} (chan={CHAN2}, lat={LAT2}ms)")
        print(f"    • Combined sink → {COMB}")
        print("[*] Monitoring for disconnects...")

        monitor_thread = threading.Thread(target=monitor_sinks)
        monitor_thread.start()

        while not stop_flag.is_set():
            time.sleep(1)

    finally:
        cleanup()

if __name__ == '__main__':
    main()
