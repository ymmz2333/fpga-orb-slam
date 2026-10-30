"""Create a teammate source handoff without local credentials, caches or videos."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[2]

README='''# ORB60 队友源码交接包 — 2026-10-26

这是当前软件工作源码，以及 2026-10-25 原交接包之上的修改。原压缩包保留；
本包不包含 bitstream、内核、BOOT、原视频、NPU 权重或本机账号/SSH 密钥。
已有 bitstream 沿用 ORB 4PPC / 150MHz + HDMI 配套版本，不需要重新布局布线。

## 先看哪里

- `zynq7015_demo/src/demo_main.cpp`：本次实际构建和上板的 PS 应用入口。
  不要把旧的独立 `src/main.cpp` 当成本轮板端入口。
- `zynq7015_demo/src/slam.cpp`、`include/zslam/motion.hpp`：匹配缓存与时间感知预测。
- `zynq7015_demo/include/zslam/pipeline.hpp`、`affinity.hpp`：缓冲所有权与线程调度。
- `zynq7015_demo/src/ui.cpp`、`include/zslam/dense_environment.hpp`：稠密环境显示。
  稠密数据只用于 Dashboard，定位、匹配、PnP 仍然使用稀疏地图。
- `orb60/demo_bridge`：协议、地图 V2、构建部署、录像启动、RK 自启动。
- `orb60/viewer/egl_raster_view.py`：已验证的 Mali GPU 后端。
  GPU 用独立 EGL FBO 绘制，再由普通 Qt 窗口显示，避免原生合成黑窗。
  `gles_view.py` 的原生窗口路径是历史实验，不是当前默认后端。
- `orb60/dense`：现有 NPU/深度/点云处理参考源码。模型和完整 RK ORB-SLAM3
  基础源码未重复打包；相关修改/导入脚本在 `demo_bridge/rk`、`dense/slam`。
- `evidence/README_ZH.md`：当前设备目录、启动命令、实测与限制。

## 包内配套文件

- `deployment/zynq-dense-release.tar.gz`：本轮通过 ARM 自检及录像运行的编译版。
- `deployment/recording_dense_map_20261026.tar.gz`：同录像关联地图，2400 稀疏定位点、
  130 关键帧及 140244 稠密显示点。旧 2547 点地图仍在原交接包；部署副本剔除
  147 个不满足 >=3 不同关键帧支持的点，原始坐标不变。
- `evidence`：GPU 双窗口报告、Zynq 计时/轨迹、实际 HDMI 扫描缓冲截图和编译记录。

## 构建入口

保持本包目录结构。Linux/RK 上在包根目录运行，显式传入交叉编译器和静态 JPEG：

```sh
python3 -m orb60.demo_bridge.build_arm \\
 --compiler /usr/bin/arm-linux-gnueabihf-g++-9 \\
 --jpeg-library orb60/demo_bridge/dependencies/libturbojpeg-arm.a \\
 --fully-static --with-selftests --output build/arm
```

本轮使用 GCC9 ARM hard-float 全静态编译，强制链接 pthread；实际编译版本及 SHA
见 `evidence/arm_checks.json`。一次一个编译进程，至少 1536MiB 可用内存。
`stage_zynq.py` 可以从有 PASS checks.json 的目标输出生成可部署 release。
Windows native 快速验证使用 `build_native.py --compiler <MinGW g++.exe>`，
然后执行 `test-zslam.exe <新的测试输出目录>` 和 `test-bridge.exe`。
GUI 依赖列表在 `orb60/demo_bridge/requirements-rk-gui.txt`。
GPU 入口为 `run_rk_viewer_gpu.sh`；`run_rk_viewer.sh` 默认转入该入口，
仅显式设置 `ORB60_GUI_BACKEND=software` 时使用旧软件渲染。

所有开发路径应按本机配置；不要照搬历史文档中的用户名、安装路径或 PID。
不要直接覆盖现有板卡发布版；使用新 release，校验 SHA，停止已确认的 ORB 拥有者，
再安装/切换。不要同时启动两个 PL 客户端，不自动加载 bitstream 或写 BOOT。

## 本轮验收边界

现成灰度录像 -> 实际 PL -> Zynq PS 固定地图定位/HDMI；2273 帧，2048 有效，
约 23.6FPS。CPU ORB=0，帧号/纳秒时间戳/特征数量与黄金一致；本轮未重比全部特征字节。
19 项 native、19 项 ARM 自检通过，HDMI 欠载/AXI 错误为零。
GPU 两个窗口非黑屏、原稀疏样式、旋转测试通过；这是渲染帧率，不是定位帧率。
测试时 RK 显示器断开，使用 X11/FBO 核对；接屏仍需复核。
新摄像头建图/稠密自动交接、断网运行和 Zynq SD 重启没有被本轮录像测试替代。
RK 桌面自启动已保留；Zynq 原 SD 自启动服务未更换。
录像沿用旧临时标定，不套用新摄像头内参。相对尺度，不用于真实尺寸测量。

## 离线完整性检查

解压后在本包根目录执行：

```sh
python3 verify_package.py
```

只检查本包内容完整性，不冒称完成编译、板卡或性能验收。第三方 LICENSE/NOTICE
随源码保留。
'''

VERIFY='''import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parent
manifest=json.loads((root/'SHA256SUMS.json').read_text(encoding='utf-8'))
for name,expected in manifest.items():
    p=(root/name).resolve()
    if root not in p.parents or not p.is_file():raise RuntimeError('Missing/unsafe file: '+name)
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    if h.hexdigest()!=expected:raise RuntimeError('SHA mismatch: '+name)
print('PACKAGE_INTEGRITY_PASS files='+str(len(manifest)))
'''


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise ValueError('Preserve existing delivery; choose another output')
    files={}
    for directory in ['zynq7015_demo','orb60/demo_bridge','orb60/viewer','orb60/dense']:
        for source in (ROOT/directory).rglob('*'):
            if not source.is_file() or any(part in {'__pycache__','.git','.venv','build','output','node_modules'} for part in source.relative_to(ROOT).parts):continue
            if source.suffix in {'.pyc','.pyo'}:continue
            files[source.relative_to(ROOT).as_posix()]=source
    for name in ['project_env.ps1','local_env.example.ps1','check_environment.ps1']:
        files['scripts/'+name]=ROOT/'scripts'/name
    evidence=ROOT/'orb60/build/demo_bridge/merge_20261026'
    for name in ['README_ZH.md','acceptance.json','arm_checks.json','gpu_acceptance.json','gpu_acceptance_final.json',
                 'board_timing.csv','board_poses.csv','display.json','zynq_status.json','zynq_dense_hdmi.png','dense.png','sparse.png']:
        files['evidence/'+name]=evidence/name
    for name in ['zynq-dense-release.tar.gz','recording_dense_map_20261026.tar.gz']:
        files['deployment/'+name]=evidence/name
    for name in files:
        if any(x in name.lower() for x in ['board_router_ssh','board_via_rk','rk_demo.json','local_env.ps1','id_rsa','id_ed25519','credentials']):
            raise ValueError('Private configuration must not be delivered: '+name)
    text_files={'README_FIRST_ZH.md':README.encode(),'verify_package.py':VERIFY.encode()}
    sums={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in files.items()}
    sums.update({name:hashlib.sha256(data).hexdigest() for name,data in text_files.items()})
    text_files['SHA256SUMS.json']=(json.dumps(sums,ensure_ascii=False,indent=2)+'\n').encode()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    prefix='ORB60_TEAM_SOURCE_20261026/'
    with zipfile.ZipFile(a.output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,path in sorted(files.items()):archive.write(path,prefix+name)
        for name,data in text_files.items():archive.writestr(prefix+name,data)
    with zipfile.ZipFile(a.output) as archive:
        if archive.testzip() is not None:raise RuntimeError('ZIP CRC failure')
        for name,expected in sums.items():
            if hashlib.sha256(archive.read(prefix+name)).hexdigest()!=expected:raise RuntimeError('ZIP SHA mismatch: '+name)
        if len(archive.namelist())!=len(set(archive.namelist())):raise RuntimeError('Duplicate archive path')
    digest=hashlib.sha256(a.output.read_bytes()).hexdigest()
    a.output.with_suffix('.zip.sha256').write_text(digest+'  '+a.output.name+'\n',encoding='ascii')
    print(json.dumps(dict(status='PACKAGE_INTEGRITY_PASS',files=len(sums)+1,bytes=a.output.stat().st_size,sha256=digest,path=str(a.output.resolve())),indent=2))


if __name__=='__main__':main()
