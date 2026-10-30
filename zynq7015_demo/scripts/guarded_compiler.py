"""CMake compiler entry point: check RAM before every actual compiler process."""
import subprocess,sys
from resource_guard import require_local_memory,ResourceDeferred
try:
    require_local_memory('jpeg compiler '+sys.argv[1])
    raise SystemExit(subprocess.run(sys.argv[1:]).returncode)
except ResourceDeferred as error:
    print(error,flush=True);raise SystemExit(75)
