"""Optional two-stage controller bar. Blocking network I/O stays off the Qt thread."""
import json
import threading
import urllib.request
from urllib.parse import urlparse
from PySide6 import QtCore, QtWidgets


class DemoControls(QtWidgets.QWidget):
    updated = QtCore.Signal(dict)
    failed = QtCore.Signal(str)

    def __init__(self, endpoint, parent=None):
        super().__init__(parent)
        self.endpoint = endpoint.rstrip('/')
        if urlparse(self.endpoint).scheme != 'http':
            raise ValueError('演示控制地址应为 http://RK地址:5610')
        self.lock = threading.Lock()
        self.inflight = False
        self.closed = False
        self.pending_action = None
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.buttons = {}
        for action, label in [('start_mapping', '开始异构建图'), ('finalize_and_localize', '结束建图并切换'),
                              ('relocalize', '重新定位'), ('stop', '停止')]:
            button = QtWidgets.QPushButton(label)
            button.setEnabled(False)
            button.clicked.connect(lambda _=False, a=action: self.request(a))
            row.addWidget(button)
            self.buttons[action] = button
        self.label = QtWidgets.QLabel('正在检查设备…')
        self.label.setWordWrap(True)
        self.label.setMinimumWidth(180)
        row.addWidget(self.label, 1)
        self.updated.connect(self.apply_status)
        self.failed.connect(self.apply_failure)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(1000)
        QtCore.QTimer.singleShot(0, self.poll)

    def _fetch(self, action=None):
        with self.lock:
            if self.inflight or self.closed:
                if action and not self.closed:self.pending_action = action
                return
            self.inflight = True
        def work():
            try:
                data = json.dumps(dict(action=action)).encode() if action else None
                request = urllib.request.Request(self.endpoint + ('/command' if action else '/status'), data=data,
                                                 headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(request, timeout=3) as response:
                    value = json.loads(response.read(256*1024))
                if not self.closed:
                    self.updated.emit(value)
            except Exception as exc:
                if not self.closed:
                    self.failed.emit(str(exc))
            finally:
                with self.lock:
                    self.inflight = False
                    pending=self.pending_action;self.pending_action=None
                if pending and not self.closed:self._fetch(pending)
        threading.Thread(target=work, daemon=True).start()

    def request(self, action):
        for button in self.buttons.values():
            button.setEnabled(False)
        self._fetch(action)

    def poll(self):
        self._fetch()

    def apply_status(self, value):
        state, busy = value.get('state'), value.get('busy', False)
        zynq = value.get('zynq', {})
        ready = zynq.get('hardware_verified') and not zynq.get('hardware_fault')
        self.buttons['start_mapping'].setEnabled(not busy and bool(ready) and state not in ('MAPPING', 'FINALIZING', 'INSTALLING'))
        self.buttons['finalize_and_localize'].setEnabled(not busy and state == 'MAPPING')
        self.buttons['relocalize'].setEnabled(not busy and bool(zynq.get('map_version')) and state in ('LOCAL', 'LOCAL_RELOCALIZING', 'STOPPED', 'ERROR'))
        self.buttons['stop'].setEnabled(busy or state not in ('IDLE', 'STOPPED'))
        labels = {'IDLE': '就绪：摄像头连接 Zynq', 'MAPPING': '异构建图：RK3588 计算地图',
                  'FINALIZING': '等待建图／回环优化收尾', 'INSTALLING': '传输并校验 SD 地图',
                  'LOCAL_RELOCALIZING': 'Zynq 本地重定位中，请看 HDMI', 'LOCAL': 'Zynq 独立定位有效，可以断开 RK 网线',
                  'STOPPED': '处理已停止', 'ERROR': '处理失败，未自动回退'}
        text = 'FPGA '+value.get('zynq_host','地址未提供')+' · '+labels.get(state, str(state))
        if value.get('error'):
            text += '：' + value['error'][:200]
        if value.get('capacity_warning'):
            text += ' | '+value['capacity_warning']
        if value.get('handover_stage',{}).get('stage'):
            text += ' | '+value['handover_stage']['stage']
        self.label.setText(text)

    def apply_failure(self, reason):
        self.label.setText('控制连接中断：' + reason[:180] + '；本地运行状态未知，请看 HDMI')
        for button in self.buttons.values():
            button.setEnabled(False)

    def shutdown(self):
        self.closed = True
        self.timer.stop()
