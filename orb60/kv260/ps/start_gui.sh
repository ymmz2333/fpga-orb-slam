#!/usr/bin/env bash
set -euo pipefail
root="$(cd "${1:?Usage: start_gui.sh DEPLOY_ROOT}" && pwd)"
cd "$root/sources"
# A stable latest path can be created by the run controller. No historical
# data is silently substituted when live telemetry is not yet available.
exec "$root/.venv_gui/bin/python" -m orb60.kv260.gui --dense-live 127.0.0.1:18786
