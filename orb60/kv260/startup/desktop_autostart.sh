#!/bin/sh
# GNOME supplies the actual DISPLAY/XAUTHORITY; no fixed display number.
set -eu
systemctl --user import-environment DISPLAY XAUTHORITY XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS
exec systemctl --user start orb60-manual-session.service
