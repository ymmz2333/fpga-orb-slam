#!/usr/bin/env python3
"""Request non-overlapping demo window positions through the active X11 WM."""
import ctypes as C
import re
import subprocess

class Data(C.Union):
    _fields_ = [('l',C.c_long*5)]
class Client(C.Structure):
    _fields_ = [('type',C.c_int),('serial',C.c_ulong),('send_event',C.c_int),
                ('display',C.c_void_p),('window',C.c_ulong),('message_type',C.c_ulong),
                ('format',C.c_int),('data',Data)]
class Event(C.Union):
    _fields_ = [('client',Client),('padding',C.c_long*24)]
x = C.CDLL('libX11.so.6')
x.XOpenDisplay.argtypes=[C.c_char_p]; x.XOpenDisplay.restype=C.c_void_p
x.XDefaultRootWindow.argtypes=[C.c_void_p]; x.XDefaultRootWindow.restype=C.c_ulong
x.XInternAtom.argtypes=[C.c_void_p,C.c_char_p,C.c_int]; x.XInternAtom.restype=C.c_ulong
x.XSendEvent.argtypes=[C.c_void_p,C.c_ulong,C.c_int,C.c_long,C.POINTER(Event)]
x.XFlush.argtypes=[C.c_void_p]; x.XCloseDisplay.argtypes=[C.c_void_p]
d = x.XOpenDisplay(None)
if not d:
    raise SystemExit('No X display')
tree = subprocess.check_output(['xwininfo','-root','-tree'],text=True)
count = 0
for name,left in [('Map Viewer',100),('Current Frame',1150)]:
    match = re.search(r'(0x[0-9a-f]+) "ORB-SLAM3: '+name+'"',tree)
    if not match:
        continue
    event=Event(); event.client.type=33; event.client.display=d
    event.client.window=int(match.group(1),16)
    event.client.message_type=x.XInternAtom(d,b'_NET_MOVERESIZE_WINDOW',0)
    event.client.format=32
    event.client.data.l[:]=[(1<<8)|(1<<9)|(1<<12),left,100,0,0]
    x.XSendEvent(d,x.XDefaultRootWindow(d),0,(1<<20)|(1<<19),C.byref(event))
    count += 1
x.XFlush(d); x.XCloseDisplay(d)
print('DEMO_WINDOW_POSITION_REQUEST count=%d'%count)
raise SystemExit(0 if count==2 else 1)
