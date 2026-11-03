"""Camera window status describes observed mapping state, not assumed success."""


def label(meta,sparse_points,dense_points):
    if not meta.get('pose_valid') and sparse_points==0:
        return '等待初始化，请缓慢平移相机'
    if not meta.get('pose_valid'):
        return '跟踪中断'
    if dense_points==0:
        return '建图中，等待彩色点云'
    return '彩色稠密点云'
