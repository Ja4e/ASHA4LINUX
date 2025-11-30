#!/usr/bin/env bash

# Exit immediately if not running inside Kitty
if [[ -z "${KITTY_PID}" ]]; then
    echo "This script must be run from a Kitty terminal."
    exit 1
fi

# Check if environment variables are set
if [[ -z "${PRI_O}" && -z "${SEC_O}" ]]; then

    # Check if a kitty window with title "delayer" already exists
    if ! kitty @ ls | grep -q '"title": "delayer"' ; then
        kitty @ launch \
            --location=hsplit \
            --title delayer \
            --cwd=current \
            python /home/jake/AudioStreamer/2_device_delayer.py --gtk
    fi
fi

# Move to AudioStreamer directory
cd ASHA4LINUX || exit 1

# Run connect.py with high priority
nice -10 python connect.py -d -r -rof -da
