"""Install reversible PS boot/session services and GDM automatic login."""
import argparse,hashlib,json,os,re,shutil,subprocess,uuid
from pathlib import Path


def automatic_login(text,user):
    if not re.fullmatch('[a-z_][a-z0-9_-]*',user):raise ValueError('Invalid local login name')
    match=re.search(r'^\[daemon\][ \t]*$',text,re.M)
    if not match:raise ValueError('GDM daemon section missing')
    tail=text[match.end():];next_section=re.search(r'^\[',tail,re.M);end=match.end()+(next_section.start() if next_section else len(tail))
    section=text[match.end():end]
    for key,value in [('AutomaticLoginEnable','true'),('AutomaticLogin',user),('WaylandEnable','false')]:
        pattern=r'^[ \t]*'+key+r'[ \t]*=.*$'
        if re.search(pattern,section,re.M):section=re.sub(pattern,key+'='+value,section,flags=re.M)
        else:section+='\n'+key+'='+value+'\n'
    return text[:match.end()]+section.rstrip('\n')+'\n\n'+text[end:]


def main():
    import pwd
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--user',default='ubuntu');p.add_argument('--install',action='store_true');a=p.parse_args()
    if not a.install or os.geteuid()!=0:raise ValueError('Explicit root --install required')
    root=a.root.resolve();owner=pwd.getpwnam(a.user);home=Path(owner.pw_dir);source=root/'sources/orb60/kv260/startup'
    if any(c.isspace() for c in str(root)):raise ValueError('Service root requires a path without whitespace')
    backup=root/'startup_install_backups'/uuid.uuid4().hex;backup.mkdir(parents=True)
    paths=dict(base_preparation='platform_dpu_points/tagged_assets_20261103_a/PREPARATION.json',
        phased_manifest='platform_dpu_points/tagged_phased_20261103_a/PHASED.json',
        tagged_export='platform_dpu_points/tagged_assets_20261103_a/TAGGED_EXPORT.json',
        release='platform_dpu_points/tagged_assets_20261103_a/release_manifest.json',
        abi='platform_dpu_points/tagged_assets_20261103_a/point_abi.json',
        module='vendor/xlnx_dpu_vivado_2022_1/xlnx_dpu.ko',arch='models/arch.json',profile='models/target_profile.json',
        runtime='sources/orb60/kv260/depth/runtime_exec.sh',camera_config='manual_camera_system.json')
    pinned=set(v for k,v in paths.items() if k!='camera_config')
    for relative in ['platform_dpu_points/tagged_assets_20261103_a','platform_dpu_points/tagged_phased_20261103_a']:
        pinned.update(str(f.relative_to(root)) for f in (root/relative).iterdir() if f.is_file())
    pinned.update(str(f.relative_to(root)) for f in source.iterdir() if f.is_file() and f.suffix in ('.py','.sh'))
    pinned.update('sources/orb60/kv260/point_pl/'+name for name in ('deploy_phased.py','deploy_board.py','config_identity.py','board_smoke.py'))
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    config=dict(user=a.user,paths=paths,expected_xrt_prefix='2.13',sha256={rel:sha(root/rel) for rel in sorted(pinned)})
    if sha(root/paths['module'])!='b3e40a05a349e692c410144c86b4c4ec29ae0c117a1be21fcce4837f08f13773':raise ValueError('Unexpected DPU module')
    def write(target,text,user=False,executable=False):
        target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            dest=backup/str(target).lstrip('/');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,dest)
        target.write_text(text,encoding='utf-8');target.chmod(0o755 if executable else 0o644)
        if user:os.chown(target,owner.pw_uid,owner.pw_gid)
    write('/etc/orb60/startup.json',json.dumps(config,indent=2)+'\n')
    system_unit=f'''[Unit]
Description=ORB60 verified KV260 DPU and point platform at cold boot
Requires=dfx-mgr.service
After=local-fs.target dfx-mgr.service systemd-udevd.service
Before=display-manager.service

[Service]
Type=oneshot
WorkingDirectory={root}/sources
ExecStart=/usr/bin/python3 {source}/boot_platform.py --root {root} --config /etc/orb60/startup.json
RemainAfterExit=yes
TimeoutStartSec=240
Restart=no

[Install]
WantedBy=multi-user.target
'''
    write('/etc/systemd/system/orb60-platform.service',system_unit)
    user_unit=f'''[Unit]
Description=ORB60 manual mapping and continuous latest-map localization
PartOf=graphical-session.target

[Service]
Type=simple
WorkingDirectory={root}/sources
ExecStart=/usr/bin/python3 {source}/desktop_session.py --root {root}
ExecStop=/usr/bin/python3 {source}/stop_session.py --root {root}
TimeoutStopSec=120
Restart=no
'''
    unit=home/'.config/systemd/user/orb60-manual-session.service';write(unit,user_unit,user=True)
    entry=f'''[Desktop Entry]
Type=Application
Name=ORB60 手动建图与持续定位
Exec=/bin/bash {source}/desktop_autostart.sh
Terminal=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=3
'''
    write(home/'.config/autostart/orb60-manual-session.desktop',entry,user=True)
    # The entire user config directory belongs to the account, including newly
    # created parent directories. No password or sudo authentication is changed.
    for folder in (home/'.config/autostart',home/'.config/systemd',home/'.config/systemd/user'):
        os.chown(folder,owner.pw_uid,owner.pw_gid)
    gdm=Path('/etc/gdm3/custom.conf');write(gdm,automatic_login(gdm.read_text(),a.user))
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','orb60-platform.service'],check=True)
    subprocess.run(['runuser','-u',a.user,'--','env','XDG_RUNTIME_DIR=/run/user/'+str(owner.pw_uid),
        'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/'+str(owner.pw_uid)+'/bus','systemctl','--user','daemon-reload'],check=True)
    result=dict(status='AUTOSTART_INSTALLED_NOT_REBOOT_VERIFIED',backup=str(backup),automatic_login=a.user,
                root_service='orb60-platform.service',desktop_service='orb60-manual-session.service',
                automatic_mapping=False,automatic_localization=True,no_password_or_sudo_policy_change=True,
                no_kernel_or_boot_image_change=True,config_sha256=sha(Path('/etc/orb60/startup.json')))
    (backup/'INSTALL.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
