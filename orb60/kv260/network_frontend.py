"""7015 Ethernet ORB adapter for the KV260 PS fixed-map client.

Uses the retained wire validator. No local FPGA access or feature fallback.
"""
import socket
import numpy as np
from orb60.linux.client import Client


def endpoint(value):
    if value.startswith('['):
        end=value.find(']')
        if end<1 or value[end+1:end+2]!=':':raise ValueError('Expected [IPv6%interface]:port')
        host,port=value[1:end],value[end+2:]
    else:
        if value.count(':')!=1:raise ValueError('Expected host:port or [IPv6%interface]:port')
        host,port=value.rsplit(':',1)
    if not host or not port.isdecimal() or not 1<=int(port)<=65535:raise ValueError('Invalid ORB endpoint')
    return host,int(port)


class NetworkFrontend:
    def __init__(self,address):
        host,port=endpoint(address)
        self.client=Client(host,port,timeout=15,allow_simulated=False)
        self.client.sock.settimeout(15)
        self.previous=-1;self.stamp=0;self.failed=False

    def run(self,gray,frame,stamp):
        if self.failed:raise RuntimeError('Failed connection cannot be reused')
        if gray.dtype!=np.uint8 or gray.shape!=(720,960):raise ValueError('Expected original 960x720 GRAY8')
        if type(frame)!=int or type(stamp)!=int or frame!=self.previous+1 or stamp<=self.stamp:
            raise ValueError('Missing/reordered source frame or timestamp')
        try:
            # Wire sequence starts at1, while source indices start at0.
            result,payload=self.client.extract(np.ascontiguousarray(gray).tobytes(),frame+1,stamp,0)
            if result['simulated']:raise ValueError('Actual PL required')
        except BaseException:
            self.failed=True;self.close();raise
        self.previous,self.stamp=frame,stamp
        return payload,result

    def close(self):
        try:self.client.sock.shutdown(socket.SHUT_RDWR)
        except OSError:pass
        self.client.close()
