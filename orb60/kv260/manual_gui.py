"""Small local operator panel; heavy map display stays in the existing Mali path."""
import argparse,json,os,subprocess,sys,time,uuid
from pathlib import Path
from PySide6 import QtCore,QtGui,QtWidgets
from .manual_control import submit


class Window(QtWidgets.QWidget):
    def __init__(self,root,config,connection,library,existing=None,qa=None,startup_screenshot=False):
        super().__init__();self.root=root;self.qa=qa;self.qa_index=0;self.qa_started=time.monotonic();self.qa_failed=False
        self.folder=root/'manual_sessions'/('manual_'+time.strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid())+'_'+uuid.uuid4().hex[:8])
        self.startup_screenshot=startup_screenshot
        self.setWindowTitle('KV260 手动建图与定位');self.resize(760,185)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint,True)
        layout=QtWidgets.QVBoxLayout(self);self.status=QtWidgets.QLabel('正在启动控制程序');self.status.setWordWrap(True);layout.addWidget(self.status)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row);self.buttons={}
        for action,label in [('start_mapping','开始建图'),('stop_mapping','结束并保存')]:
            button=QtWidgets.QPushButton(label);button.setEnabled(False);button.clicked.connect(lambda checked=False,a=action:submit(self.folder,a));row.addWidget(button);self.buttons[action]=button
        self.restart_button=QtWidgets.QPushButton('重启程序');self.restart_button.clicked.connect(self.restart_application);row.addWidget(self.restart_button)
        hide=QtWidgets.QPushButton('隐藏面板');hide.clicked.connect(self.hide);row.addWidget(hide)
        self.detail=QtWidgets.QLabel('结束建图后自动下发最新地图并持续定位；关闭面板不停止定位。');self.detail.setWordWrap(True);layout.addWidget(self.detail)
        self.setStyleSheet('QWidget{background:#101b25;color:#e5edf3;font-size:16px} QPushButton{padding:10px;background:#294453;border:1px solid #557886} QPushButton:disabled{color:#78838c;background:#1b2933}')
        self.folder.parent.mkdir(parents=True,exist_ok=True)
        cmd=['bash',str(root/'sources/orb60/kv260/depth/runtime_exec.sh'),str(root),'python','-m','orb60.kv260.manual_control',
             '--config',str(config),'--connection',str(connection),'--library',str(library),'--folder',str(self.folder)]
        if existing:cmd+=['--existing-map',str(existing)]
        self.log=(self.folder.parent/(self.folder.name+'.log')).open('wb')
        self.child=subprocess.Popen(cmd,cwd=root/'sources',stdout=self.log,stderr=subprocess.STDOUT)
        self.closed=False;self.controller_dead=False;self.restart_pending=False;self.restart_report=None;self.want_close=False;self.timer=QtCore.QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(200)
    def restart_application(self):
        if self.restart_pending:return
        try:
            from .manual_restart import request
            self.restart_report=request(self.root,os.getpid());self.restart_pending=True;self.restart_button.setEnabled(False)
            self.status.setText('正在保存并重启程序，请等待；最新地图会保留')
            for button in self.buttons.values():button.setEnabled(False)
            if self.controller_dead:
                self.closed=True;self.close();QtWidgets.QApplication.instance().quit()
        except BaseException as error:self.status.setText('重启未启动：'+str(error));self.restart_button.setEnabled(True)
    def tick(self):
        if self.restart_pending and self.restart_report and self.restart_report.exists():
            restart=json.loads(self.restart_report.read_text())
            if restart['status']=='FAILED':
                self.restart_pending=False;self.restart_button.setEnabled(True);self.status.setText('重启失败：'+restart.get('error','请查看记录'))
        show=self.folder.parent/'show_panel'
        if show.exists():
            show.unlink();self.showNormal();self.raise_();self.activateWindow()
        path=self.folder/'status.json'
        if path.exists():
            state=json.loads(path.read_text());self.status.setText(state['message'])
            labels=dict(IDLE='待机',MAP_READY='地图待用',WAIT_NETWORK='等待两板网络',RECONNECTING='正在恢复两板连接',NETWORK_DRAIN='换线等待中',STARTING_MAP='正在启动建图',MAPPING='建图中',SAVING='正在结束并保存',STARTING_LOCAL='正在启动定位',LOCALIZING='定位中',STOPPING_LOCAL='正在停止定位',ERROR='需要处理',CLOSED='已退出')
            self.detail.setText('状态：'+labels.get(state['phase'],state['phase'])+'　地图：'+state.get('map_label','尚未建立'))
            if state['phase']=='LOCALIZING' and state.get('active_run'):
                progress=Path(state['active_run'])/'live_progress.json'
                try:self.detail.setText(self.detail.text()+'　已发送 %s 帧'%json.loads(progress.read_text())['frames_sent'])
                except (OSError,ValueError,KeyError):pass
            for action,b in self.buttons.items():b.setEnabled(state['buttons'][action] and not self.restart_pending and not self.controller_dead)
            if self.restart_pending:self.status.setText('正在保存并重启：'+state['message'])
            if self.startup_screenshot and state['phase'] in ('MAP_READY','IDLE'):
                self.grab().save(str(self.folder/'ready.png'));self.startup_screenshot=False
            if self.qa:
                if (state['phase']=='ERROR' or time.monotonic()-self.qa_started>480) and not self.qa_failed:
                    self.qa_failed=True;self.grab().save(str(self.folder/'qa_error.png'));submit(self.folder,'quit')
                if self.qa_index<len(self.qa['steps']):
                    step=self.qa['steps'][self.qa_index]
                    enough=True
                    if step.get('min_frames') and state['phase']==step['phase']:
                        active=Path(state['active_run']);progress=active/'processing_progress.json'
                        if state['phase']=='MAPPING':enough=progress.is_file() and json.loads(progress.read_text()).get('frames',0)>=step['min_frames']
                        else:
                            sent=active/'sent_frames.csv';enough=sent.is_file() and len(sent.read_text().splitlines())-1>=step['min_frames']
                    if state['phase']==step['phase'] and enough and time.monotonic()-self.qa_started>=step.get('after',0):
                        if step.get('screenshot'):self.grab().save(str(self.folder/step['screenshot']))
                        if step['action']=='quit':submit(self.folder,'quit') # explicit QA maintenance only
                        elif step['action']=='restart_program':self.restart_button.click()
                        else:self.buttons[step['action']].click()
                        self.qa_index+=1
            if state['phase']=='CLOSED':
                if self.qa:(self.folder/'QA.json').write_text(json.dumps(dict(status='FAILED' if self.qa_failed or self.qa_index!=len(self.qa['steps']) else 'BUTTON_SEQUENCE_COMPLETED',steps=self.qa_index))+'\n')
                self.closed=True;self.child.wait(timeout=10);self.log.close();self.close();QtWidgets.QApplication.instance().quit()
        if self.child.poll() is not None and not self.closed and not self.controller_dead:
            self.status.setText('控制程序已退出，请查看记录：'+str(self.folder.parent/(self.folder.name+'.log')))
            for b in self.buttons.values():b.setEnabled(False)
            self.controller_dead=True;self.restart_button.setEnabled(not self.restart_pending)
            if self.restart_pending or self.qa:
                self.closed=True
                if self.qa:self.qa_failed=True
                self.close();QtWidgets.QApplication.instance().quit()
    def closeEvent(self,event):
        if self.closed:event.accept()
        else:
            self.hide();event.ignore()


def main():
    p=argparse.ArgumentParser()
    for n in ('root','config','connection','library'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--existing-map',type=Path);p.add_argument('--qa-script',type=Path);p.add_argument('--startup-screenshot',action='store_true')
    a=p.parse_args()
    import fcntl
    sessions=a.root.resolve()/'manual_sessions';sessions.mkdir(parents=True,exist_ok=True)
    lock=(sessions/'manual_gui.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        (sessions/'show_panel').touch();lock.close();return 0
    app=QtWidgets.QApplication(sys.argv);app.setQuitOnLastWindowClosed(False)
    font=QtGui.QFont('Noto Sans CJK SC',11);app.setFont(font)
    view=Window(a.root.resolve(),a.config.resolve(),a.connection.resolve(),a.library.resolve(),a.existing_map,
                json.loads(a.qa_script.read_text()) if a.qa_script else None,a.startup_screenshot)
    view.show();code=app.exec();return 2 if view.qa_failed else code

if __name__=='__main__':raise SystemExit(main())
