"""Per-process/thread scheduling only; no system governor or persistent changes."""
import os
from pathlib import Path


def validate_policy(config,allowed):
    core=config.get('tracking_core')
    if core is None:return None
    background=config.get('background_cores')
    if type(core)!=int or not isinstance(background,list) or not background or any(type(c)!=int for c in background):
        raise ValueError('Integer tracking core and background core list required')
    if len(set(background))!=len(background) or core in background or not ({core}|set(background))<=set(allowed):
        raise ValueError('Tracking/background cores must be distinct and available')
    return core,tuple(background)


def pin_current_threads(cores):
    cores=set(cores)
    if not cores:raise ValueError('Empty CPU affinity')
    for path in Path('/proc/self/task').iterdir():
        try:os.sched_setaffinity(int(path.name),cores)
        except ProcessLookupError:pass
