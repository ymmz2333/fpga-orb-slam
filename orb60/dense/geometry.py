"""CPU geometry in OpenCV camera coordinates (right, down, forward)."""
import numpy as np


def letterbox_geometry(width, height, k, target=(960, 720)):
    tw, th = target
    scale = min(tw / width, th / height)
    rw, rh = int(round(width * scale)), int(round(height * scale))
    x, y = (tw-rw)//2, (th-rh)//2
    # Actual rounded dimensions matter, especially for odd camera sizes.
    sx, sy = rw/width, rh/height
    transform = np.array([[sx, 0, x+(sx-1)/2], [0, sy, y+(sy-1)/2], [0, 0, 1.]])
    return transform @ np.asarray(k), (x, y, rw, rh), transform


def valid_pose(twc):
    twc = np.asarray(twc)
    if twc.shape != (4, 4) or not np.isfinite(twc).all():
        return False
    r = twc[:3, :3]
    return (np.max(np.abs(twc[3] - [0, 0, 0, 1])) < 1e-6 and
            np.linalg.norm(r.T @ r-np.eye(3)) < .005 and abs(np.linalg.det(r)-1) < .005)


def camera_points(world, twc):
    if not valid_pose(twc):
        raise ValueError("Invalid Twc")
    return (np.asarray(world)-twc[:3, 3]) @ twc[:3, :3]


def project(world, k, twc):
    xyz = camera_points(world, twc)
    p = xyz @ np.asarray(k).T
    uv = p[:, :2] / p[:, 2:3]
    return uv, xyz[:, 2]


def backproject(uv, z, k, twc):
    if not valid_pose(twc):
        raise ValueError("Invalid Twc")
    uv = np.asarray(uv)
    z = np.asarray(z)
    if not np.isfinite(z).all() or np.any(z <= 0):
        raise ValueError("Invalid camera depth")
    rays = np.c_[uv, np.ones(len(uv))] @ np.linalg.inv(k).T
    return (rays*z[:, None]) @ twc[:3, :3].T + twc[:3, 3]


def sample_bilinear(image, uv):
    image = np.asarray(image)
    uv = np.asarray(uv)
    h, w = image.shape[:2]
    inside = (np.isfinite(uv).all(axis=1) & (uv[:, 0] >= 0) & (uv[:, 1] >= 0) &
              (uv[:, 0] < w-1) & (uv[:, 1] < h-1))
    values = np.full(len(uv), np.nan)
    u, v = uv[inside].T
    x, y = np.floor(u).astype(int), np.floor(v).astype(int)
    dx, dy = u-x, v-y
    values[inside] = ((1-dx)*(1-dy)*image[y, x] + dx*(1-dy)*image[y, x+1] +
                      (1-dx)*dy*image[y+1, x] + dx*dy*image[y+1, x+1])
    return values


def fit_inverse_depth(prediction, z, seed=0, minimum=20):
    """RANSAC followed by robust IRLS; no independent per-frame normalization."""
    prediction, z = np.asarray(prediction), np.asarray(z)
    ok = np.isfinite(prediction) & np.isfinite(z) & (z > 1e-6)
    x, y = prediction[ok], 1/z[ok]
    if len(x) < minimum:
        raise ValueError("fewer_than_20_valid_correspondences")
    spread = np.percentile(x, 90)-np.percentile(x, 10)
    if spread < 1e-6 * max(1., abs(float(np.median(x)))):
        raise ValueError("degenerate_network_prediction")
    tolerance = .08*float(np.median(y))
    rng = np.random.RandomState(seed % (2**32))
    best = None
    for _ in range(256):
        i, j = rng.choice(len(x), 2, replace=False)
        if abs(x[j]-x[i]) < spread*.1:
            continue
        slope = (y[j]-y[i])/(x[j]-x[i])
        if slope <= 0:
            continue
        intercept = y[i]-slope*x[i]
        error = np.abs(slope*x+intercept-y)
        good = error < tolerance
        score = (int(good.sum()), -float(np.median(error[good])) if good.any() else -np.inf)
        if best is None or score > best[0]:
            best = score, slope, intercept, good
    if best is None or best[3].sum() < minimum:
        raise ValueError("insufficient_robust_depth_inliers")
    mask = best[3]
    # Center/scale the design matrix to avoid numerical issues with MiDaS values.
    center, scale = np.median(x[mask]), np.std(x[mask])
    if scale < spread*.05:
        raise ValueError("degenerate_fit_inliers")
    design = np.c_[(x[mask]-center)/scale, np.ones(mask.sum())]
    target = y[mask]
    weight = np.ones(len(target))
    for _ in range(8):
        fitted = np.linalg.lstsq(design*weight[:, None], target*weight, rcond=None)[0]
        residual = np.abs(design@fitted-target)
        delta = max(1e-8, 1.5*np.median(residual))
        weight = np.sqrt(np.minimum(1., delta/np.maximum(residual, 1e-12)))
    slope, intercept = fitted[0]/scale, fitted[1]-fitted[0]*center/scale
    if slope <= 0 or not np.isfinite([slope, intercept]).all():
        raise ValueError("invalid_inverse_depth_fit")
    residual = np.abs(slope*x+intercept-y)
    inliers = residual < tolerance
    if inliers.sum() < minimum:
        raise ValueError("insufficient_final_depth_inliers")
    return float(slope), float(intercept), dict(correspondences=len(x), inliers=int(inliers.sum()),
        median_relative_inverse_error=float(np.median(residual[inliers]/y[inliers])))


def consistent_points(world, views, tolerance=.08):
    """Require support from at least one other view; reject occluded/disagreeing pixels."""
    support = np.zeros(len(world), dtype=bool)
    for depth, mask, k, twc in views:
        uv, z = project(world, k, twc)
        observed = sample_bilinear(depth, uv)
        validity = sample_bilinear(mask.astype(np.float32), uv)
        finite = np.isfinite(observed) & np.isfinite(z) & np.isfinite(validity)
        good=np.zeros(len(world),dtype=bool)
        good[finite] = ((validity[finite] > .99) & (z[finite] > 0) &
                        (np.abs(observed[finite]-z[finite]) <= tolerance*z[finite]))
        support |= good
    return support


class VoxelMap:
    """Bounded weighted voxel centroids; deterministic rebinning when capacity is exceeded."""
    def __init__(self, edge, capacity=2000000):
        if edge <= 0 or capacity < 1:
            raise ValueError("Invalid voxel size/capacity")
        self.edge, self.capacity = float(edge), capacity
        self.sums = np.empty((0, 6), np.float64)
        self.counts = np.empty(0, np.int64)
        self.resolutions = [self.edge]

    def add(self, points, colors):
        points, colors = np.asarray(points), np.asarray(colors)
        if points.shape != colors.shape or points.ndim != 2 or points.shape[1] != 3:
            raise ValueError("Point/color shape mismatch")
        if not np.isfinite(points).all() or not np.isfinite(colors).all():
            raise ValueError("Nonfinite fusion input")
        sums = np.vstack((self.sums, np.c_[points, colors]))
        counts = np.r_[self.counts, np.ones(len(points), np.int64)]
        while len(counts):
            keys = np.floor(sums[:, :3]/counts[:, None]/self.edge).astype(np.int64)
            _, inverse = np.unique(keys, axis=0, return_inverse=True)
            n = int(inverse.max())+1
            reduced = np.empty((n, 6), np.float64)
            for j in range(6):
                reduced[:, j] = np.bincount(inverse, weights=sums[:, j], minlength=n)
            totals = np.bincount(inverse, weights=counts, minlength=n).astype(np.int64)
            sums, counts = reduced, totals
            if n <= self.capacity:
                break
            self.edge *= 2
            self.resolutions.append(self.edge)
        self.sums, self.counts = sums, counts

    def arrays(self):
        mean = self.sums/self.counts[:, None]
        return mean[:, :3].astype(np.float32), np.clip(np.rint(mean[:, 3:]), 0, 255).astype(np.uint8)
