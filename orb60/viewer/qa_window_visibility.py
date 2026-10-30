"""Check native visibility of an otherwise empty own Qt window; no processing input."""
import ctypes
import json
from pathlib import Path
import sys
from PySide6 import QtCore,QtWidgets

app=QtWidgets.QApplication([])
window=QtWidgets.QWidget();window.setWindowTitle('ORB Studio - window visibility QA')
window.resize(320,160);window.show();result={}
def check():
    ctypes.windll.user32.IsWindowVisible.argtypes=[ctypes.c_void_p]
    visible=bool(ctypes.windll.user32.IsWindowVisible(int(window.winId())))
    result.update(status='PASS' if visible else 'FAIL',native_visible=visible)
    Path(sys.argv[1]).write_text(json.dumps(result,indent=2));window.close()
QtCore.QTimer.singleShot(500,check);app.exec()
if not result.get('native_visible'):raise RuntimeError('The native Qt window was hidden')
