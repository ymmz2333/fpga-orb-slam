"""Headless Qt control layout and asynchronous HTTP behavior; no device requests."""
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6 import QtWidgets,QtTest
from PySide6 import QtGui

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'orb60/viewer'))
from demo_controls import DemoControls
from orb60.demo_bridge.controller import Controller


class Controls(unittest.TestCase):
    def test_connect_button_uses_controller_start_in_demo_mode(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from app import Window
        controls=SimpleNamespace(request=Mock())
        window=SimpleNamespace(args=SimpleNamespace(demo_controller='http://127.0.0.1:5610'),demo_run='old',demo_controls=controls)
        Window.reconnect_source(window)
        self.assertIsNone(window.demo_run)
        controls.request.assert_called_once_with('start_mapping')
    @classmethod
    def setUpClass(cls):
        cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        if os.name=='nt' and not QtGui.QFontDatabase.families():
            font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/msyh.ttc'
            if font.is_file():
                index=QtGui.QFontDatabase.addApplicationFont(str(font))
                families=QtGui.QFontDatabase.applicationFontFamilies(index)
                if families:cls.app.setFont(QtGui.QFont(families[0],10))

    def test_buttons_preflight_mapping_handover_and_failure(self):
        value={'state':'IDLE','busy':False,'zynq':{'hardware_verified':False,'hardware_fault':False}}
        actions=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):self.reply(value)
            def do_POST(self):
                actions.append(json.loads(self.rfile.read(int(self.headers['Content-Length'])))['action']);self.reply(value)
            def reply(self,data):
                body=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self,*_):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        widget=DemoControls('http://127.0.0.1:'+str(server.server_port));widget.resize(1200,70);widget.show()
        def wait_for(predicate):
            deadline=time.monotonic()+4
            while time.monotonic()<deadline:
                QtTest.QTest.qWait(20)
                if predicate():return
            raise AssertionError('Qt request did not complete')
        try:
            wait_for(lambda:not widget.inflight)
            self.assertFalse(widget.buttons['start_mapping'].isEnabled())
            value['zynq']['hardware_verified']=True;widget.poll()
            wait_for(lambda:widget.buttons['start_mapping'].isEnabled())
            widget.buttons['start_mapping'].click();wait_for(lambda:'start_mapping' in actions)
            value.update(state='MAPPING');widget.poll();wait_for(lambda:widget.buttons['finalize_and_localize'].isEnabled())
            widget.buttons['finalize_and_localize'].click();wait_for(lambda:'finalize_and_localize' in actions)
            value.update(state='FINALIZING',busy=True);widget.poll()
            wait_for(lambda:widget.buttons['stop'].isEnabled() and not widget.buttons['finalize_and_localize'].isEnabled())
            value.update(state='LOCAL',busy=False);value['zynq']['map_version']='a'*64;widget.poll()
            wait_for(lambda:'可以断开' in widget.label.text())
            out=ROOT/'orb60/build/demo_bridge/controls.png';out.parent.mkdir(parents=True,exist_ok=True);widget.grab().save(str(out))
            widget.apply_failure('test disconnect');self.assertTrue(all(not b.isEnabled() for b in widget.buttons.values()))
        finally:
            widget.shutdown();widget.close();server.shutdown();server.server_close();thread.join(timeout=1)

    def test_failed_physical_preflight_never_spawns_tracker(self):
        controller=Controller(dict(camera=str(ROOT/'orb60/demo_bridge/config/camera_orb.csv')))
        controller.zcommand=lambda action:dict(hardware_verified=False,hardware_fault=False,mode='WAITING',calibration_sha256='wrong')
        with patch('orb60.demo_bridge.controller.subprocess.Popen') as spawn:
            controller.action('start_mapping')
            deadline=time.monotonic()+2
            while controller.busy and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(controller.state,'ERROR');spawn.assert_not_called()


if __name__=='__main__':unittest.main()
