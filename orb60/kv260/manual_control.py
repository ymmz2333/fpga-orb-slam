"""Manual mapping, followed by automatic current-map handoff and continuous localization."""
import argparse,json,os,subprocess,sys,time,uuid
from pathlib import Path
from .run_network_system import load,save,digest


def allowed(phase,has_map,waiting_intent=None):
    idle=phase in ('IDLE','MAP_READY','ERROR')
    return dict(start_mapping=idle or phase in ('LOCALIZING','WAIT_NETWORK'),stop_mapping=phase in ('STARTING_MAP','MAPPING') or (phase=='WAIT_NETWORK' and waiting_intent=='mapping'),
                quit=phase!='CLOSED') # quit is maintenance-only, never a normal UI button.


def submit(folder,action):
    if action not in allowed('IDLE',False):raise ValueError('Unknown manual action')
    folder=Path(folder)
    if not folder.is_dir():raise FileNotFoundError('Manual controller has not started')
    queue=folder/'commands';queue.mkdir(parents=True,exist_ok=True)
    name='%020d_%s'%(time.monotonic_ns(),uuid.uuid4().hex)
    save(queue/(name+'.json'),dict(action=action))


class Session:
    def __init__(self,config,connection,library,folder,existing=None):
        self.config_path=Path(config).resolve();self.config=load(self.config_path);self.root=Path(self.config['root']).resolve()
        self.connection_path=Path(connection).resolve();self.connection=load(self.connection_path);self.library=Path(library).resolve()
        self.folder=Path(folder).resolve();self.folder.mkdir(parents=True,exist_ok=False);(self.folder/'commands').mkdir()
        self.phase='IDLE';self.message='等待操作';self.handoff=Path(existing).resolve() if existing else None;self.map_label='无地图'
        self.job=None;self.log=None;self.kind=None;self.run=None;self.stop_file=None;self.stop_pending=False;self.quitting=False;self.counter=0
        self.processed=set();self.installed=None;self.events=[];self.pending_mapping=False
        from .peer_link import PeerLink
        self.network=PeerLink(self.root,self.connection,self.folder,self.root/self.config['camera'])
        self.waiting_intent=None;self.next_network_attempt=0;self.network_lost=False;self.loss_journal_size=0
        if self.handoff:
            from .install_camera_map_7015 import check_handoff
            proof,_,_=check_handoff(self.handoff,allow_camera_diagnostic=True,allow_manual_latest=True)
            camera=self.root/self.config['camera']
            if digest(camera)!=proof['source']['camera_sha256']:raise ValueError('Existing map belongs to a different camera')
            self.phase='MAP_READY';self.map_label='上次保存的地图';self.message='已有摄像头地图，正在恢复持续定位'
        self.publish()

    def publish(self):
        save(self.folder/'status.json',dict(phase=self.phase,message=self.message,buttons=allowed(self.phase,self.handoff is not None,getattr(self,'waiting_intent',None)),
             map_available=self.handoff is not None,map_label=getattr(self,'map_label','已有地图' if self.handoff else '无地图'),handoff=str(self.handoff) if self.handoff else None,
             active_run=str(self.run) if self.run else None,quit_pending=self.quitting,waiting_intent=getattr(self,'waiting_intent',None),events=self.events[-100:]))

    def spawn(self,kind,command):
        self.log=(self.folder/(kind+'_%03d.log'%self.counter)).open('wb')
        self.job=subprocess.Popen(command,cwd=self.root/'sources',stdout=self.log,stderr=subprocess.STDOUT,start_new_session=True)
        self.kind=kind;self.events.append(dict(event='START',kind=kind,pid=self.job.pid,monotonic_ns=time.monotonic_ns()))
        self.network_lost=False;self.waiting_intent=None

    def wait_network(self,intent,reason):
        self.waiting_intent=intent;self.phase='WAIT_NETWORK';self.next_network_attempt=time.monotonic()+2
        self.message='等待两板网络；直接连接KV260与7015后自动'+('开始已请求的建图' if intent=='mapping' else '恢复最新地图定位')
        self.events.append(dict(event='NETWORK_WAIT',intent=intent,reason=str(reason),monotonic_ns=time.monotonic_ns()));self.publish()

    def peer_ready(self,intent):
        network=getattr(self,'network',None)
        if network is None:return True # Unit fixtures/legacy non-network lifecycle.
        if not network.available():self.wait_network(intent,'peer unavailable');return False
        self.phase='RECONNECTING';self.message='两板网络已连接，正在确认接收程序与资源';self.publish()
        try:network.prepare()
        except BaseException as error:
            from .peer_link import PeerBusy
            if isinstance(error,PeerBusy) or not network.available(force=True):
                self.wait_network(intent,error);return False
            raise
        return True

    def start_mapping(self):
        if not self.peer_ready('mapping'):return
        self.counter+=1;self.run=self.folder/('mapping_%03d'%self.counter);self.stop_file=self.folder/('stop_mapping_%03d'%self.counter)
        self.stop_pending=False;self.pending_mapping=False;self.phase='STARTING_MAP';self.message='正在加载建图程序，稍后缓慢平移相机'
        self.spawn('mapping',[sys.executable,'-m','orb60.kv260.run_camera_system','--config',str(self.config_path),
              '--output',str(self.run),'--frames','0','--manual-stop-file',str(self.stop_file)])

    def start_localization(self):
        if not self.peer_ready('localization'):return
        self.counter+=1;self.phase='STARTING_LOCAL';self.message='正在下发最新地图并启动持续定位';self.publish()
        from .two_board_session import Board
        from .install_camera_map_7015 import install,reuse,check_handoff
        proof,_,_=check_handoff(self.handoff,allow_camera_diagnostic=True,allow_manual_latest=True)
        target=self.folder/('install_%03d'%self.counter);target.mkdir()
        release='/opt/orb-demo/kv260_network_camera_manual_'+self.folder.name+'_'+str(self.counter)
        board=Board(self.root,self.connection,target);cache=self.root/'manual_installed_map.json'
        installed=reuse(board,self.handoff,load(cache)) if cache.exists() else None
        if installed is None:
            installed=install(board,self.handoff,release,allow_camera_diagnostic=True,allow_manual_latest=True)
        save(cache,installed)
        save(target/'RESULT.json',installed);self.installed=installed
        self.run=self.folder/('localization_%03d'%self.counter);self.stop_file=self.folder/('stop_localization_%03d'%self.counter)
        self.stop_pending=False
        self.spawn('localization',[sys.executable,'-m','orb60.kv260.run_7015_network_localization','--root',str(self.root),
            '--connection',str(self.connection_path),'--release',installed['release'],'--endpoint','['+self.connection['host']+']:5605',
            '--mode','live_camera','--frames','0','--camera',str(self.root/self.config['camera']),
            '--source-camera',str(self.root/self.config['source_camera']),'--library',str(self.library),
            '--output',str(self.run),'--manual-stop-file',str(self.stop_file)])
        self.publish()

    def resume(self):
        if self.handoff:
            try:self.start_localization()
            except BaseException as e:
                if getattr(self,'network',None) and not self.network.available(force=True):self.wait_network('localization',e)
                else:self.phase='ERROR';self.message=str(e);self.events.append(dict(event='RESUME_FAILED',error=str(e)));self.publish()

    def action(self,action):
        buttons=allowed(self.phase,self.handoff is not None,getattr(self,'waiting_intent',None))
        if action not in buttons or not buttons[action]:
            raise ValueError('当前状态不允许该操作')
        self.events.append(dict(event='OPERATOR',action=action,monotonic_ns=time.monotonic_ns()))
        if action=='start_mapping':
            if self.kind=='localization' and self.job:
                self.pending_mapping=True;self.stop_pending=True;self.phase='STOPPING_LOCAL';self.message='正在交还摄像头与PL，随后开始新建图'
            else:self.start_mapping()
        elif action=='stop_mapping':
            if self.phase=='WAIT_NETWORK':
                if self.handoff:self.wait_network('localization','operator canceled queued mapping')
                else:self.waiting_intent=None;self.phase='IDLE';self.message='已取消等待建图'
            else:self.stop_pending=True;self.phase='SAVING';self.message='正在结束采集、优化地图并保存彩色点云，请等待'
        elif action=='quit':
            self.quitting=True
            if self.job:
                self.stop_pending=True;self.phase='SAVING' if self.kind=='mapping' else 'STOPPING_LOCAL';self.message='正在安全结束并保存，请等待'
            else:self.phase='CLOSED';self.message='已退出'
        self.publish()

    def tick(self):
        if not self.job:
            if self.phase=='WAIT_NETWORK' and time.monotonic()>=self.next_network_attempt:
                try:
                    if self.waiting_intent=='mapping':self.start_mapping()
                    elif self.waiting_intent=='localization':self.start_localization()
                except BaseException as error:
                    if not self.network.available(force=True):self.wait_network(self.waiting_intent,error)
                    else:self.phase='ERROR';self.message=str(error);self.events.append(dict(event='RECONNECT_FAILED',error=str(error)));self.publish()
            return
        network=getattr(self,'network',None)
        if network and self.kind=='localization' and not self.stop_pending:
            sent=self.run/'sent_frames.csv';size=sent.stat().st_size if sent.exists() else 0
            if not network.carrier_up() and not self.network_lost:
                self.network_lost=True;self.loss_journal_size=size;self.phase='NETWORK_DRAIN'
                self.message='两板网络已断开，保留地图并等待直连网线；控制面板继续运行'
                self.events.append(dict(event='LINK_DOWN',monotonic_ns=time.monotonic_ns()));self.publish()
            elif self.network_lost and network.carrier_up() and size>self.loss_journal_size:
                self.network_lost=False;self.phase='LOCALIZING';self.message='网络已恢复，继续定位'
                self.events.append(dict(event='SAME_STREAM_LINK_RESTORED',monotonic_ns=time.monotonic_ns()));self.publish()
        control=self.run.with_name(self.run.name+'_control')
        # Do not race startup's fresh-stop-file validation.
        ready=(control/'RESULT.json').exists() if self.kind=='mapping' else (self.run/'localizer.log').exists()
        if self.stop_pending and ready:self.stop_file.touch(exist_ok=True)
        if self.phase=='STARTING_MAP' and (self.run/'processing_started.json').exists():
            self.phase='MAPPING';self.message='建图中；结束时点击“结束并保存”';self.publish()
        if self.phase=='STARTING_LOCAL' and (self.run/'sent_frames.csv').exists():
            self.phase='LOCALIZING';self.message='持续定位中；7015 HDMI显示彩色背景与实时轨迹';self.publish()
        code=self.job.poll()
        if code is None:return
        self.log.close();self.log=None;self.job=None
        self.events.append(dict(event='DRAINED',kind=self.kind,exit_code=code,monotonic_ns=time.monotonic_ns()))
        try:
            if not self.quitting and self.kind=='localization' and (self.run/'RESULT.json').is_file():
                result=load(self.run/'RESULT.json')
                if result.get('transport_disconnect'):
                    self.wait_network('mapping' if self.pending_mapping else 'localization',result.get('error','network stream interrupted'));return
            if (not self.quitting and not self.stop_pending and self.kind=='mapping' and network and
                not (self.run/'processing_started.json').exists() and not network.available(force=True)):
                self.wait_network('mapping','network interrupted before mapping started');return
            if not self.stop_pending:
                result_path=control/'RESULT.json' if self.kind=='mapping' else self.run/'RESULT.json'
                reason=load(result_path).get('error','处理程序意外结束，请查看本轮日志') if result_path.exists() else '处理程序意外结束，请查看本轮日志'
                front=control/'frontend.log'
                if self.kind=='mapping' and front.exists() and 'No space left on device' in front.read_text(errors='replace')[-5000:]:reason='7015存储空间不足，无法创建建图运行目录'
                raise ValueError(reason)
            if self.kind=='mapping':
                result=load(control/'RESULT.json')
                if result['status']=='ACTUAL_CAMERA_SYSTEM_COMPONENT_PASS_NO_MAP_INITIALIZED':
                    self.phase='MAP_READY' if self.handoff else 'IDLE';self.message='本次未初始化地图；原有地图保留。请缓慢平移后重新建图' if self.handoff else '本次未初始化地图，请缓慢平移后重新建图'
                else:
                    if result['status'] not in ('ACTUAL_STABLE_MAP_DPU_GPU_COMPONENT_PASS','FAILED_TARGET_GATES'):raise ValueError(result.get('error','建图保存失败'))
                    from .handoff_camera_7015 import create
                    candidate=self.folder/('handoff_%03d'%self.counter)
                    proof=create(self.run,self.root/self.config['camera'],candidate,manual_latest=True)
                    self.handoff=candidate;self.map_label='本次保存的地图';save(self.root/'manual_latest_map.json',dict(handoff=str(candidate),camera_sha256=proof['source']['camera_sha256']))
                    self.events.append(dict(event='CURRENT_MAP_SAVED',map_id=proof['source']['map_id'],handoff=str(candidate),
                                            original_failed_gates=proof['source']['failed_gates']))
                    self.phase='MAP_READY';self.message='最新地图已保存，正在自动切换定位'
                if self.handoff and not self.quitting:self.start_localization()
            else:
                result=load(self.run/'RESULT.json')
                if not result.get('operator_stop_requested'):raise ValueError(result.get('error','定位没有正常停止'))
                if result['status']!='ACTUAL_7015_NATIVE_NETWORK_COLOR_LOCALIZATION_COMPONENT_PASS' and result.get('error')!="ValueError('No native fixed-map localization')":
                    raise ValueError(result.get('error','定位停止后的完整性检查失败'))
                self.phase='MAP_READY';self.message='定位已停止，轨迹已保存（有效帧 %s）'%result.get('valid_poses',0)
                if self.pending_mapping and not self.quitting:self.start_mapping()
            if self.quitting:self.phase='CLOSED';self.message='已保存并退出'
        except BaseException as e:
            if (getattr(self,'network',None) and self.job is None and self.phase in ('STARTING_LOCAL','RECONNECTING') and
                not self.network.available(force=True)):
                self.wait_network('localization',e);return
            self.events.append(dict(event='STAGE_FAILED',kind=self.kind,error=str(e)))
            self.phase='ERROR';self.message=str(e)
            if self.quitting:self.phase='CLOSED';self.message='已结束；本轮失败记录和最新已保存地图保留：'+str(e)
            if self.kind=='mapping':
                try:
                    failures=load(control/'RESULT.json').get('failed_gates',[]);reasons=[]
                    if any('below5FPS' in f for f in failures):reasons.append('完整几何速度未达目标')
                    if reasons:self.message='新图未用于定位：'+'、'.join(reasons)+'。上次地图保留。'
                except (OSError,ValueError):pass
        self.publish()

    def command(self,action):
        try:self.action(action)
        except BaseException as e:
            self.events.append(dict(event='REJECTED',action=action,error=str(e)))
            if self.job is None and self.phase in ('STARTING_MAP','STARTING_LOCAL','RECONNECTING'):
                if getattr(self,'network',None) and not self.network.available(force=True):
                    self.wait_network('mapping' if action=='start_mapping' else 'localization',e)
                else:self.phase='ERROR';self.message=str(e)
            self.publish()


def main():
    p=argparse.ArgumentParser()
    for n in ('config','connection','library','folder'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--existing-map',type=Path);a=p.parse_args()
    import fcntl
    lock=a.folder.parent/'manual_control.lock';lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        app=Session(a.config,a.connection,a.library,a.folder,a.existing_map)
        app.resume()
        while app.phase!='CLOSED':
            for command in sorted((app.folder/'commands').glob('*.json')):
                if command.name in app.processed:continue
                app.processed.add(command.name)
                try:app.command(load(command)['action'])
                except BaseException as e:
                    app.events.append(dict(event='REJECTED',file=command.name,error=str(e)));app.publish()
            app.tick();time.sleep(.1)
    return 0

if __name__=='__main__':raise SystemExit(main())
