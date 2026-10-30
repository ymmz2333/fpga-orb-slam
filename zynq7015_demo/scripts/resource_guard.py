"""Small, read-only Windows RAM gate for serial local compiler processes."""
import ctypes,os

class ResourceDeferred(RuntimeError):pass

def require_local_memory(operation,minimum_mib=1536):
    if os.name!='nt':return None
    class Memory(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(name,ctypes.c_ulonglong) for name in
            ['total_phys','avail_phys','total_page','avail_page','total_virtual','avail_virtual','avail_extended']]
    memory=Memory();memory.length=ctypes.sizeof(memory)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raise ResourceDeferred('RAM status unavailable; defer local compiler: '+operation)
    available=memory.avail_phys/(1024*1024)
    if available<minimum_mib:
        raise ResourceDeferred(f'DEFERRED_MEMORY {operation}: free={available:.0f}MiB, required={minimum_mib}MiB; retry after resources recover')
    return available

if __name__=='__main__':print(f'LOCAL_AVAILABLE_MIB={require_local_memory("preflight"):.0f}')
