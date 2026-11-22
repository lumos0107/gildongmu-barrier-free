"""공개 지도 땅 높이 격자(설계 6장 다).

1) 1:1,000 등고선(5 m, 꼭짓점을 2 m 간격으로 촘촘히)과 표고점을 선형 보간(볼록 껍질 밖은 가장 가까운 값)
2) 2 m 가우스 흐림
3) 옹벽·석축(높이 > 0.3 m): 매끈한 땅의 오르막 쪽에 +높이/2, 내리막 쪽에 −높이/2.
   벽에서 1 m 안은 그대로, 1~6 m에서 0으로 줄인다.
격자는 virtual_world.Terrain(정사각, Unity 좌표)이다.
"""
import math

import numpy as np
import shapely
from pyproj import Transformer
from scipy.interpolate import griddata
from scipy.ndimage import gaussian_filter, map_coordinates

import common  # noqa: F401  (sys.path 준비)
import virtual_world as vw
from common import attr_float, shape_of

_T = Transformer.from_crs(4326, 5186, always_xy=True)
WALL_NEAR, WALL_FAR = 1.0, 6.0


def _grid_5186(geo, n, cell, origin):
    ax = origin + np.arange(n) * cell
    UX, UZ = np.meshgrid(ax, ax)  # [z, x]
    px = UX / geo.mpp + geo.W / 2
    py = geo.H / 2 - UZ / geo.mpp
    lon = (geo.ox + px) / geo.n * 360 - 180
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (geo.oy + py) / geo.n))))
    X, Y = _T.transform(lon, lat)
    return np.asarray(X), np.asarray(Y)


def _samples(feats, bounds, step=2.0):
    minx, miny, maxx, maxy = bounds
    pts, vals = [], []
    for f in feats:
        if f["code"] == "F0010000" and f["gtype"] == "L":
            v = attr_float(f, "등고수치", None)
            if v is None:
                continue
            ln = shape_of(f)
            if ln.geom_type != "LineString":
                continue
            x0, y0, x1, y1 = ln.bounds
            if x1 < minx or x0 > maxx or y1 < miny or y0 > maxy:
                continue
            k = max(2, int(ln.length / step) + 1)
            for d in np.linspace(0, ln.length, k):
                p = ln.interpolate(d)
                pts.append((p.x, p.y)), vals.append(v)
        elif f["code"] == "F0020000" and f["gtype"] == "P":
            v = attr_float(f, "수치", None)
            x, y = f["geom"][0]
            if v is not None and minx <= x <= maxx and miny <= y <= maxy:
                pts.append((x, y)), vals.append(v)
    return np.array(pts), np.array(vals)


def _sample_grid(h, X0, Y0, xs, ys, origin_xy, inv):
    """5186 점들의 격자 높이(격자는 5186에서 거의 평행이동·회전이 작음 → 역변환 행렬로 칸 좌표)."""
    q = np.c_[xs - origin_xy[0], ys - origin_xy[1]] @ inv.T
    return map_coordinates(h, [q[:, 1], q[:, 0]], order=1, mode="nearest")


def build_terrain(feats, geo, cell=2.0, walls=True) -> vw.Terrain:
    """walls=False면 옹벽 끊김 없이 매끈한 땅(길 높이를 정할 때 쓴다)."""
    n = int(math.ceil(geo.size_m / cell)) + 1
    origin = -geo.size_m / 2
    X, Y = _grid_5186(geo, n, cell, origin)
    pad = 150.0
    bounds = (X.min() - pad, Y.min() - pad, X.max() + pad, Y.max() + pad)
    P, V = _samples(feats, bounds)
    key = np.round(P * 2) / 2
    uniq, inv_idx = np.unique(key, axis=0, return_inverse=True)
    inv_idx = inv_idx.ravel()
    uv = np.bincount(inv_idx, V) / np.bincount(inv_idx)
    grid = np.c_[X.ravel(), Y.ravel()]
    H = griddata(uniq, uv, grid, method="linear")
    far = np.isnan(H)
    if far.any():
        H[far] = griddata(uniq, uv, grid[far], method="nearest")
    H = gaussian_filter(H.reshape(n, n), sigma=1.0)

    # 5186 -> 칸 좌표(아핀 근사): 칸 (i=x, j=z)일 때 X = X00 + A @ (i, j)
    A = np.array([[X[0, 1] - X[0, 0], X[1, 0] - X[0, 0]], [Y[0, 1] - Y[0, 0], Y[1, 0] - Y[0, 0]]])
    inv = np.linalg.inv(A)
    o = (X[0, 0], Y[0, 0])
    smooth = H.copy()
    add = np.zeros_like(H)
    for f in (feats if walls else []):
        if f["code"] != "F0040000" or f["gtype"] != "L":
            continue
        h = attr_float(f, "높이")
        if h <= 0.3:
            continue
        ln = shape_of(f)
        if ln.geom_type != "LineString" or ln.length < 0.5:
            continue
        x0, y0, x1, y1 = ln.bounds
        if x1 < X.min() or x0 > X.max() or y1 < Y.min() or y0 > Y.max():
            continue
        # 오르막 쪽: 가운데에서 양쪽 3 m 매끈한 땅 비교
        m = ln.interpolate(0.5, normalized=True)
        a, b = ln.interpolate(max(0.0, ln.length / 2 - 0.5)), ln.interpolate(min(ln.length, ln.length / 2 + 0.5))
        tx, ty = b.x - a.x, b.y - a.y
        tl = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / tl, tx / tl
        hl, hr = _sample_grid(smooth, X, Y, np.array([m.x + 3 * nx, m.x - 3 * nx]), np.array([m.y + 3 * ny, m.y - 3 * ny]), o, inv)
        up_left = 1.0 if hl >= hr else -1.0
        # 띠 안의 칸
        c = np.c_[[x0 - WALL_FAR, x1 + WALL_FAR, x0 - WALL_FAR, x1 + WALL_FAR], [y0 - WALL_FAR, y0 - WALL_FAR, y1 + WALL_FAR, y1 + WALL_FAR]]
        ij = (c - o) @ inv.T
        i0, i1 = int(max(0, np.floor(ij[:, 0].min()))), int(min(n - 1, np.ceil(ij[:, 0].max())))
        j0, j1 = int(max(0, np.floor(ij[:, 1].min()))), int(min(n - 1, np.ceil(ij[:, 1].max())))
        if i1 < i0 or j1 < j0:
            continue
        xs, ys = X[j0:j1 + 1, i0:i1 + 1].ravel(), Y[j0:j1 + 1, i0:i1 + 1].ravel()
        pts = shapely.points(xs, ys)
        d = shapely.distance(pts, ln)
        t = shapely.line_locate_point(ln, pts)
        pa = shapely.line_interpolate_point(ln, np.maximum(t - 0.3, 0))
        pb = shapely.line_interpolate_point(ln, np.minimum(t + 0.3, ln.length))
        ax_, ay_ = shapely.get_x(pa), shapely.get_y(pa)
        bx_, by_ = shapely.get_x(pb), shapely.get_y(pb)
        cross = (bx_ - ax_) * (ys - ay_) - (by_ - ay_) * (xs - ax_)  # >0 이면 선의 왼쪽
        side = np.where(cross >= 0, 1.0, -1.0) * up_left
        w = np.clip((WALL_FAR - d) / (WALL_FAR - WALL_NEAR), 0, 1)
        add[j0:j1 + 1, i0:i1 + 1] += (side * h / 2 * w).reshape(j1 - j0 + 1, i1 - i0 + 1)
    return vw.Terrain(n=n, cell=cell, origin=origin, h=H + add)


def height_5186(ter, geo, x, y) -> float:
    return ter.height(*geo.unity_from5186(x, y))


def spot_report(ter, geo, spots) -> list:
    """[(값, 격자, 격자 − 값)]. 격자 밖 점은 뺀다."""
    out = []
    half = ter.cell * (ter.n - 1) / 2
    for f in spots:
        v = attr_float(f, "수치", None)
        if v is None:
            v = attr_float(f, "NUME", None)
        if v is None:
            continue
        ux, uz = geo.unity_from5186(*f["geom"][0])
        if abs(ux) > half or abs(uz) > half:
            continue
        g = ter.height(ux, uz)
        out.append((v, g, g - v))
    return out
