"""Activate only an explicitly identified ORB Studio window on its X11 desktop."""
import argparse,ctypes,subprocess
p=argparse.ArgumentParser();p.add_argument('window',type=lambda v:int(v,0));p.add_argument('pid',type=int);a=p.parse_args()
info=subprocess.check_output(['xprop','-id',hex(a.window),'_NET_WM_PID','WM_CLASS'],text=True)
if 'ORB Studio' not in info or ('= '+str(a.pid)) not in info:
    raise RuntimeError('Window ownership differs; no desktop action performed')
x=ctypes.CDLL('libX11.so.6')
x.XOpenDisplay.argtypes=[ctypes.c_char_p];x.XOpenDisplay.restype=ctypes.c_void_p
x.XDefaultRootWindow.argtypes=[ctypes.c_void_p];x.XDefaultRootWindow.restype=ctypes.c_ulong
x.XInternAtom.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_int];x.XInternAtom.restype=ctypes.c_ulong
class Data(ctypes.Union):_fields_=[('b',ctypes.c_char*20),('l',ctypes.c_long*5)]
class Client(ctypes.Structure):
    _fields_=[('type',ctypes.c_int),('serial',ctypes.c_ulong),('send_event',ctypes.c_int),('display',ctypes.c_void_p),
              ('window',ctypes.c_ulong),('message_type',ctypes.c_ulong),('format',ctypes.c_int),('data',Data)]
class Event(ctypes.Union):_fields_=[('client',Client),('pad',ctypes.c_long*24)]
x.XSendEvent.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int,ctypes.c_long,ctypes.POINTER(Event)]
x.XMapRaised.argtypes=[ctypes.c_void_p,ctypes.c_ulong];x.XFlush.argtypes=[ctypes.c_void_p];x.XCloseDisplay.argtypes=[ctypes.c_void_p]
d=x.XOpenDisplay(None)
if not d:raise RuntimeError('Cannot open selected X11 display')
root=x.XDefaultRootWindow(d)
for message,values in [('_NET_WM_DESKTOP',[0,2]),('_NET_MOVERESIZE_WINDOW',[0x2f00,24,48,1500,900]),('_NET_ACTIVE_WINDOW',[2,0,0])]:
    e=Event();e.client.type=33;e.client.display=d;e.client.window=a.window;e.client.message_type=x.XInternAtom(d,message.encode(),0);e.client.format=32
    for i,v in enumerate(values):e.client.data.l[i]=v
    x.XSendEvent(d,root,0,(1<<19)|(1<<20),ctypes.byref(e))
x.XMapRaised(d,a.window);x.XFlush(d);x.XCloseDisplay(d)
print('ORB_WINDOW_ACTIVATED',hex(a.window))
