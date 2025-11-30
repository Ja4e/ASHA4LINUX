#!/usr/bin/env bash

# Exit immediately if not running inside Kitty
if [[ -z "${KITTY_PID}" ]]; then
    echo "This script must be run from a Kitty terminal."
    exit 1
fi

# Check if environment variables are set
if [[ -z "${PRI_O}" && -z "${SEC_O}" ]]; then
    # Neither PRI_O nor SEC_O is set, launch kitty split
    kitty @ launch --location=hsplit --title delayer --cwd=current python ~/ASHA4LINUX/2_device_delayer.py --gtk
fi

# Move to ASHA4LINUX directory
cd ASHA4LINUX || { echo "Failed to enter ASHA4LINUX directory"; exit 1; }

# Run connect.py with nice
nice -10 python connect.py -d -r -rof -da
