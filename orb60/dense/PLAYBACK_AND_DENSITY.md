# 回放与点云密度修复 — 2026-10-22

结果查看请双击工作区根目录的 `Launch-ORB-Dense-Result.cmd`。本机默认已切到
`orb60/build/dense/room_full_detail/result.json`，并关联原始视频；自动开始
2,273 帧离线回放，支持暂停、拖动、变速和播完重新播放。

当前默认 `Launch-ORB-Dense.cmd` 已改为实际增量处理，见 [实时处理说明](LIVE_PROCESSING.md)。

这里回放原视频与**同一次最终 SLAM 轨迹**，显示最终融合地图；不是重新运行
在线稠密建图。初始未定位帧没有相机位置。原测量只保存关键帧二维观测，
因此仅在真实关键帧显示特征，普通帧明确标注未记录。未伪造逐帧特征。
没有原片时可回放包内 130 张真实关键帧；通过“选择彩色原片”恢复完整视频，
需匹配 SHA256。各个地图独立播放。

## 密度和近看

| 项目 | 旧结果 | 细化结果 |
|---|---:|---:|
| 实际导出彩色点 | 140,244 | **1,086,538** |
| 归一化体素边长 | 0.010 | **0.004** |
| 有效深度关键帧 | 79 | 79 |
| 多视角支持的输入像素 | 8,517,060 | 8,517,060 |

复用已验收 NPU 深度、原 RGB 和最终位姿，不重跑 FPGA/SLAM/网络推理。
保持逐两像素采样和原多视角检查，没有放宽阈值或插值制造新点。
RK3588 细化融合实测 **116.24 秒**，峰值 RSS **690.75 MiB**。
旧结果和原交付包保留。

“点大小随缩放调整”默认开启，以世界坐标中的体素间距控制点的覆盖范围。
“点覆盖”可手动调节。放大或平移后，显示器优先选取当前视野内的真实点，
仍最多同时显示 20 万点；导出 PLY 保留完整 108 万点。
这只是点渲染，不是网格、补洞或精度提升。

## 验证证据

`room_full_detail/refinement_acceptance.json`：237 个缓存输入 SHA256、
相同模型与视频、8,517,060 个支持像素、位姿/稀疏地图、RGB 完整性通过。

`room_full_detail/decoder_acceptance.json`：首个关键帧、中段、末段、末帧的
新解码器快速定位与顺序解码**逐字节一致**。旧的逐帧跨越定位在 GUI
回归中超时，现仅在稠密离线回放使用新解码器快速定位，保留实时源行为。

`room_full_detail/viewer_playback/acceptance.json`：真实 GUI 自动播放、
暂停、定位、末尾重播、关键帧位姿/观测、随缩放调节点大小、近景点选择、
完整 RGB PLY 导出通过。`qa_dense_playback.py`、`qa_dense_decoder.py` 可复现。

正常 Qt 事件循环连续运行 9 秒，显示 270 帧，实测 **29.996 FPS**；
帧间隔 P99 **48.29 ms**。见 `viewer_playback/normal_loop_metrics.json`。
回放按原始时间戳推进；重绘过慢时允许略过中间显示帧，不改变已完成的
全帧 SLAM 或 NPU 处理。QtTest 操作测试中的循环速度不作为正常播放性能。

原片存在少量 H.264 解码警告；上述抽查定位与顺序输出一致，未隐藏警告。
不同平台的 FFmpeg 仍可能有少量颜色舍入差异。

## 重建边界

当前 MiDaS Small 的深度只有 256×256；输入还使用临时内参。墙面/货架可能
出现厚度、弯曲和边缘模糊。更多点主要减少采样空隙，不能消除这些几何误差。
未观测区域保持为空，不作为可测量尺寸或避障距离。

细化入口：

```sh
python3 -m dense.refine --source <accepted-result> --output <new-directory> \
  --source-frames <dataset>/frames.csv --voxel 0.004 --pixel-step 2
python3 dense/scripts/verify_refinement.py --source <accepted-result> --result <new-directory>
```

源结果只读；使用独立输出目录，原 NPU 模型和深度哈希可追溯。
