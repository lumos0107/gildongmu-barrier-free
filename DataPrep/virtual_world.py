"""민속촌 가상 세계 설계도(virtual_world.json)를 만든다.

설계: Docs/2026-11-15-가상세계-설계.md, 계획: Docs/2026-11-15-가상세계-작업계획.md
- 땅: 임의의 완만한 언덕(2 m 격자). 나중에 DEM으로 바꿀 때 Terrain만 바꾼다.
- 구간: 1 m 간격 높이 단면. 마디 높이는 최소제곱으로 맞춘다(OSM 경사 태그 구간은 그 경사).
- 좌표: Unity 맵 자료와 같다(x = 동쪽 m, z = 북쪽 m). s는 구간 첫 마디(a)에서 잰 m.
가상 값이다. 실제 민속촌 상태가 아니다.
"""
import argparse
import json
import math
import pathlib
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from scipy.interpolate import griddata
from scipy.ndimage import gaussian_filter
from scipy.spatial import cKDTree

CELL = 2.0
EVENING_TOOLS = pathlib.Path(r"C:\Users\seungjun\Documents\work\베리어프리\Barrier-free-information-gathering-app\tools")
RISER = 0.15  # 계단 한 칸 높이 m
TREAD = 0.35  # 계단 한 칸 길이 m
MATERIALS = ["asphalt", "concrete", "block", "slab", "stone", "gravel", "songi", "soil", "grass", "deck", "rubber", "coir", "other"]
GRADES = ["good", "intermediate", "bad", "very_bad"]
OSM_MAT = {"asphalt": "asphalt", "dirt": "soil", "gravel": "gravel", "paving_stones": "block"}
NOGO_WAY = "w1292606362"  # OSM 휠체어 불가 자갈 보도


@dataclass
class Inputs:
    segs: list
    pack: dict
    net: dict
    osm: dict
    size_m: float
    steps: list = field(default_factory=list)  # Unity 맵 자료의 계단 선
    map_data: dict = field(default_factory=dict)  # Unity 맵 자료 전체(건물·경계)
    site_dir: object = None  # 장소 폴더(항공사진·지도 캡처)


@dataclass
class Terrain:
    n: int
    cell: float
    origin: float
    h: np.ndarray  # [z 칸, x 칸]

    def height(self, x, z):
        fx = np.clip((x - self.origin) / self.cell, 0, self.n - 1 - 1e-9)
        fz = np.clip((z - self.origin) / self.cell, 0, self.n - 1 - 1e-9)
        ix, iz = int(fx), int(fz)
        tx, tz = fx - ix, fz - iz
        h = self.h
        return float((h[iz, ix] * (1 - tx) + h[iz, ix + 1] * tx) * (1 - tz) + (h[iz + 1, ix] * (1 - tx) + h[iz + 1, ix + 1] * tx) * tz)


@dataclass
class Profile:
    s: np.ndarray
    h: np.ndarray


def _rd(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


def load_inputs(map_path, pack_path, net_path, osm_path) -> Inputs:
    mp = _rd(map_path)
    pack = _rd(pack_path)
    pack.pop("aerial", None)
    return Inputs(segs=mp["segs"], pack=pack, net=_rd(net_path), osm=_rd(osm_path), size_m=float(mp["sizeM"]), steps=mp.get("steps", []),
                  map_data=mp, site_dir=pathlib.Path(net_path).parent)


def make_terrain(size_m: float, seed: int) -> Terrain:
    rng = np.random.default_rng(seed)
    n = int(math.ceil(size_m / CELL)) + 1
    origin = -size_m / 2
    ax = origin + np.arange(n) * CELL
    X, Z = np.meshgrid(ax, ax)  # X[z, x]
    h = np.zeros((n, n))
    for _ in range(4):
        a, sig = rng.uniform(2, 6), rng.uniform(80, 150)
        cx, cz = rng.uniform(-250, 250, 2)
        h += a * np.exp(-((X - cx) ** 2 + (Z - cz) ** 2) / (2 * sig ** 2))
    l1, l2 = rng.uniform(40, 80, 2)
    p1, p2 = rng.uniform(0, 2 * math.pi, 2)
    h += 0.3 * np.sin(2 * math.pi * X / l1 + p1) * np.sin(2 * math.pi * Z / l2 + p2)
    h -= h.min()
    rngh = h.max()
    if rngh > 11:
        h *= 11 / rngh
    elif rngh < 3:
        h *= 3 / rngh
    return Terrain(n=n, cell=CELL, origin=origin, h=h)


def seg_points(seg):
    return np.array(seg["p"], float).reshape(-1, 2)


def point_at(seg, s):
    """구간 선 위 s(m) 자리의 (x, z)와 진행 방향 단위 벡터. 선 길이를 구간 길이에 맞춰 늘이거나 줄인다."""
    pts = seg_points(seg)
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
    t = s / seg["len"] * d[-1]
    i = int(np.clip(np.searchsorted(d, t, side="right") - 1, 0, len(pts) - 2))
    u = (t - d[i]) / max(d[i + 1] - d[i], 1e-9)
    p = pts[i] + (pts[i + 1] - pts[i]) * u
    v = pts[i + 1] - pts[i]
    return p, v / max(np.hypot(*v), 1e-9)


def stations(length):
    s = list(np.arange(0.0, length, 1.0))
    if length - s[-1] < 1e-6:
        s[-1] = length
    else:
        s.append(length)
    return np.array(s)


def node_heights(inp: Inputs, ter: Terrain, stair_drops: dict = None) -> dict:
    """stair_drops: {구간: a→b 계단 높이 차(m)}. 그 구간은 땅 높이 차 + 계단 높이 차가 되게 맞춘다."""
    stair_drops = stair_drops or {}
    ends = {}
    for sg in inp.segs:
        pts = seg_points(sg)
        ends.setdefault(sg["a"], pts[0])
        ends.setdefault(sg["b"], pts[-1])
    ids = sorted(ends)
    col = {k: i for i, k in enumerate(ids)}
    T = {k: ter.height(*ends[k]) for k in ids}
    sign = _inc_signs(inp, T)
    rows, rhs, wts = [], [], []
    for sg in inp.segs:
        a, b = sg["a"], sg["b"]
        if a == b:
            continue
        r = np.zeros(len(ids))
        r[col[b]], r[col[a]] = 1, -1
        # 높이 차 오차가 아니라 기울기 오차(높이 차 / 길이)를 줄인다: 짧은 구간이 높이 차를 떠안아 가팔라지지 않게
        per_len = 1.0 / max(sg["len"], 1.0)
        if sg["id"] in stair_drops:
            rows.append(r), rhs.append(T[b] - T[a] + stair_drops[sg["id"]]), wts.append(50.0 * per_len)
        elif sg["inc"]:
            rows.append(r), rhs.append(sign[sg["id"]] * sg["len"] * max(sg["inc"]) / 100), wts.append(50.0 * per_len)
        else:
            rows.append(r), rhs.append(T[b] - T[a]), wts.append(per_len)
    for k in ids:
        r = np.zeros(len(ids))
        r[col[k]] = 1
        rows.append(r), rhs.append(T[k]), wts.append(0.01)
    W = np.array(wts)
    sol = np.linalg.lstsq(np.array(rows) * W[:, None], np.array(rhs) * W, rcond=None)[0]
    return {k: float(sol[col[k]]) for k in ids}


def _inc_signs(inp: Inputs, T: dict) -> dict:
    """경사 태그 구간의 오르내림 방향(+1: a→b 오름). 기본은 땅 기울기를 따른다.
    태그 구간끼리 고리를 이루면 고리가 닫히는(높이가 맞는) 방향 조합을 모두 따져 고른다."""
    inc = [sg for sg in inp.segs if sg["inc"] and sg["a"] != sg["b"]]
    sign = {sg["id"]: (1 if T[sg["b"]] - T[sg["a"]] >= 0 else -1) for sg in inc}
    adj = {}
    for sg in inc:
        adj.setdefault(sg["a"], []).append(sg)
        adj.setdefault(sg["b"], []).append(sg)
    seen = set()
    for start in list(adj):
        if start in seen:
            continue
        comp_nodes, comp_segs, stack = {start}, {}, [start]
        while stack:
            u = stack.pop()
            for sg in adj[u]:
                comp_segs[sg["id"]] = sg
                v = sg["b"] if sg["a"] == u else sg["a"]
                if v not in comp_nodes:
                    comp_nodes.add(v), stack.append(v)
        seen |= comp_nodes
        segs = list(comp_segs.values())
        if len(segs) < len(comp_nodes) or len(segs) > 14:
            continue  # 고리가 없거나 너무 큼
        best = None
        for mask in range(1 << len(segs)):
            sg_sign = {sg["id"]: (1 if mask >> i & 1 else -1) for i, sg in enumerate(segs)}
            pot, miss, used, q = {start: 0.0}, 0.0, set(), [start]
            while q:
                u = q.pop(0)
                for sg in adj[u]:
                    if sg["id"] in used:
                        continue
                    used.add(sg["id"])
                    d = sg_sign[sg["id"]] * sg["len"] * max(sg["inc"]) / 100
                    v, dv = (sg["b"], d) if sg["a"] == u else (sg["a"], -d)
                    if v in pot:
                        miss += (pot[u] + dv - pot[v]) ** 2
                    else:
                        pot[v] = pot[u] + dv
                        q.append(v)
            disagree = sum(sg_sign[k] != sign[k] for k in sg_sign)
            cost = (round(miss, 6), disagree)
            if best is None or cost < best[0]:
                best = (cost, sg_sign)
        sign.update(best[1])
    return sign


def make_profiles(inp: Inputs, ter: Terrain, nodes: dict) -> dict:
    out = {}
    for sg in inp.segs:
        L = sg["len"]
        s = stations(L)
        ha, hb = nodes[sg["a"]], nodes[sg["b"]]
        if sg["inc"]:
            h = ha + (hb - ha) * s / L
        else:
            T = np.array([ter.height(*point_at(sg, x)[0]) for x in s])
            h = T + (ha - T[0]) * (1 - s / L) + (hb - T[-1]) * (s / L)
        h[0], h[-1] = ha, hb
        out[sg["id"]] = Profile(s=s, h=h)
    return out


def height_at(prof: Profile, s: float) -> float:
    """같은 s가 두 번 있으면(턱) 그 s에서는 뒤 높이."""
    S, Hh = prof.s, prof.h
    if s <= S[0]:
        return float(Hh[0])
    if s >= S[-1]:
        return float(Hh[-1])
    i = int(np.searchsorted(S, s, side="right") - 1)
    return float(Hh[i] + (Hh[i + 1] - Hh[i]) * (s - S[i]) / (S[i + 1] - S[i]))


def long_deg(prof: Profile, s: float) -> float:
    L = float(prof.s[-1])
    a, b = s - 0.5, s + 0.5
    if a < 0:
        a, b = 0.0, min(1.0, L)
    if b > L:
        a, b = max(0.0, L - 1.0), L
    if b - a < 1e-9:
        return 0.0
    return math.degrees(math.atan((height_at(prof, b) - height_at(prof, a)) / (b - a)))


# ---------------------------------------------------------------------------
# 특징: 계단, 경계 경사, 턱, 좌우 기울기, 노면, 폭
# ---------------------------------------------------------------------------
def _evening(path=None):
    p = str(path or EVENING_TOOLS)
    if p not in sys.path:
        sys.path.insert(0, p)
    import evening
    return evening


def plan_points(inp: Inputs, evening_dir=None) -> dict:
    """구간별 측정 계획 지점(저녁 도구의 plan_marks 그대로, 첫 마디 a에서 출발)."""
    E = _evening(evening_dir)
    rules = inp.pack["rules"]
    by = {s["seg"]: s for s in inp.pack["segs"]}
    out = {}
    for sg in inp.segs:
        ps = by[sg["id"]]
        geo = E.geo_for(ps, ps["a"])
        out[sg["id"]] = E.plan_marks(geo["len"], geo["fine"], geo["stop"], rules, geo.get("inclines"))
    return out


def sharp_corners(seg, limit_deg: float = 30.0) -> list:
    """선 꼭짓점 중 limit_deg 넘게 꺾이는 곳의 s. 3D 띠가 안쪽에서 접히는 곳이라 턱·좌우 기울기를 피한다."""
    pts = seg_points(seg)
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
    out = []
    for i in range(1, len(pts) - 1):
        a, b = pts[i] - pts[i - 1], pts[i + 1] - pts[i]
        na, nb = np.hypot(*a), np.hypot(*b)
        if na < 1e-9 or nb < 1e-9:
            continue
        if math.degrees(math.acos(float(np.clip(a @ b / na / nb, -1, 1)))) > limit_deg:
            out.append(float(d[i] / d[-1] * seg["len"]))
    return out


def is_loop(seg) -> bool:
    """시작과 끝 마디가 같은 고리 구간. 저녁 도구는 고리를 늘 둘째 마디에서 출발한 것으로 보고
    위치(len − 표시값)와 앞뒤 부호를 뒤집는다(evening.route_input의 second)."""
    return seg["a"] == seg["b"]


def to_world(seg, m: float) -> float:
    """측정자가 읽는 표시값 m을 설계도의 s(첫 마디 a에서 잰 거리)로."""
    return seg["len"] - m if is_loop(seg) else m


def more_points(E, pack_seg, plan_pts, longs, rules) -> list:
    """경사가 3.2° 이상인 지점 앞뒤 5 m에 더 재는 지점(저녁 도구 pending_marks 그대로).
    longs는 plan_pts 순서의 측정자 방향 앞뒤 경사."""
    geo = E.geo_for(pack_seg, pack_seg["a"])
    saved = [{"mark": p["mark"], "long": v, "kind": p["kind"], "added": None, "target": None, "n": 2 if p.get("both") else 1}
             for p, v in zip(plan_pts, longs)]
    return [p for p in E.pending_marks(plan_pts, saved, geo["len"], geo["fine"], rules, geo["stop"]) if p["kind"] == "more"]


def project(seg, xy):
    """점을 구간 선에 투영: (s, 거리)."""
    pts = seg_points(seg)
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
    a, b = pts[:-1], pts[1:]
    ab = b - a
    q = np.asarray(xy, float)
    t = np.clip(((q - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-12), 0, 1)
    foot = a + ab * t[:, None]
    dist = np.hypot(*(foot - q).T)
    i = int(np.argmin(dist))
    return float((d[i] + t[i] * np.hypot(*ab[i])) / d[-1] * seg["len"]), float(dist[i])


def find_steps(inp: Inputs) -> dict:
    """Unity 맵의 계단 선을 구간에 붙인다: {구간: [(s0, s1, 칸 수)]}."""
    out = {}
    for line in inp.steps:
        p = np.array(line["p"], float).reshape(-1, 2)
        best = None
        for sg in inp.segs:
            (s0, d0), (s1, d1) = project(sg, p[0]), project(sg, p[-1])
            if max(d0, d1) <= 1.5 and (best is None or d0 + d1 < best[0]):
                best = (d0 + d1, sg, min(s0, s1), max(s0, s1))
        if best is None:
            continue
        _, sg, s0, s1 = best
        if s0 < 0.5:
            s0 = 0.0
        if s1 > sg["len"] - 0.5:
            s1 = sg["len"]
        out.setdefault(sg["id"], []).append((s0, s1, max(1, round((s1 - s0) / TREAD))))
    return out


def _stair_drops(inp, ter, steps):
    drops = {}
    for sg in inp.segs:
        for s0, s1, n in steps.get(sg["id"], []):
            t0, t1 = ter.height(*point_at(sg, s0)[0]), ter.height(*point_at(sg, s1)[0])
            drops[sg["id"]] = drops.get(sg["id"], 0.0) + (1 if t1 >= t0 else -1) * RISER * n
    return drops


def _insert(prof: Profile, x: float):
    if np.any(np.abs(prof.s - x) < 1e-9):
        return
    i = int(np.searchsorted(prof.s, x, side="right"))
    h = height_at(prof, x)
    prof.s, prof.h = np.insert(prof.s, i, x), np.insert(prof.h, i, h)


def _edit(prof: Profile, w0: float, w1: float, rel: list):
    """[w0, w1] 안의 높이를 rel([(s, w0 높이에서의 차)], 첫 점은 (w0, 0))로 바꾸고,
    바깥 구간의 기울기를 고르게 조금씩 바꿔 양 끝 높이를 지킨다."""
    _insert(prof, w0)
    _insert(prof, w1)
    s, h = prof.s, prof.h
    total = h[-1] - h[0]
    D = rel[-1][1]
    ds, dh = np.diff(s), np.diff(h)
    out = (s[1:] <= w0 + 1e-9) | (s[:-1] >= w1 - 1e-9)
    L_out = ds[out].sum()
    if L_out > 1e-9:
        k = (total - D - dh[out].sum()) / L_out
    else:
        k = 0.0
        if abs(D) > 1e-12:
            rel = [(x, y * total / D) for x, y in rel]
            D = total
    ndh = dh + k * ds
    ib = int(np.where(np.abs(s - w0) < 1e-9)[0][0])  # s가 w0인 첫 점(같은 s가 여럿이면 처음 것)
    ia = int(np.where(np.abs(s - w1) < 1e-9)[0][-1])
    hb = h[0] + np.r_[0, np.cumsum(ndh[:ib])]
    hw0 = hb[-1]
    ws = np.array([x for x, _ in rel])
    wh = hw0 + np.array([y for _, y in rel])
    ha = hw0 + D + np.r_[0, np.cumsum(ndh[ia:])]
    prof.s = np.r_[s[: ib + 1], ws[1:], s[ia + 1:]]
    prof.h = np.r_[hb, wh[1:], ha[1:]]


def _in_span(spans, s, margin=0.0, a="s0", b="s1"):
    return any(x[a] - margin <= s <= x[b] + margin for x in spans)


def _net_edges(inp):
    """연결망 선(OSM 조각)의 가운데점이 2 m 안에 드는 구간: [(구간, 속성, 조각 길이)]."""
    m = inp.pack["map"]
    n = 256 * 2 ** m["zoom"]

    def xy(lon, lat):
        s = math.sin(math.radians(lat))
        px = (lon + 180) / 360 * n - m["origin"][0]
        py = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n - m["origin"][1]
        return (px - m["W"] / 2) * m["mpp"], (m["H"] / 2 - py) * m["mpp"]

    out = []
    for f in inp.net["features"]:
        q = np.array([xy(*c) for c in f["geometry"]["coordinates"]])
        d = np.r_[0, np.cumsum(np.hypot(*np.diff(q, axis=0).T))]
        mid = (np.interp(d[-1] / 2, d, q[:, 0]), np.interp(d[-1] / 2, d, q[:, 1]))
        best, bd = None, 2.0
        for sg in inp.segs:
            dist = project(sg, mid)[1]
            if dist < bd:
                best, bd = sg["id"], dist
        if best is not None:
            out.append((best, f["properties"], float(d[-1])))
    return out


def _grade(rng, mat):
    if mat in ("asphalt", "concrete"):
        w = [0.7, 0.3, 0, 0]
    elif mat in ("block", "slab", "deck", "rubber"):
        w = [0.5, 0.4, 0.1, 0]
    else:
        w = [0, 0.4, 0.5, 0.1]
    return rng.choices(GRADES, w)[0]


def realistic_bumps(n, seed) -> list:
    """경계 사례 밖 턱 높이(11/15 팀 결정, 제주대와 같은 '현실형 섞기'): 60%는 낮은 턱 13~17 mm
    (측정 기록 시작 13 mm 이상, 22 mm 이하라 통과), 40%는 높은 턱 30~60 mm(막힘). 순서는 섞는다."""
    rb = random.Random(seed + 1000)
    n_low = round(0.6 * n)
    v = [rb.randint(13, 17) for _ in range(n_low)] + [rb.randint(30, 60) for _ in range(n - n_low)]
    rb.shuffle(v)
    return v


def add_features(inp, ter, profiles, plan, seed) -> dict:
    """구간별 특징을 정하고 profiles(높이 단면)와 ter(길 아래 땅)를 그에 맞게 바꾼다."""
    rng = random.Random(seed)
    rules = inp.pack["rules"]
    segs = sorted(inp.segs, key=lambda x: x["id"])
    feats = {sg["id"]: {"cross": [], "bumps": [], "steps": [], "surf": [], "width_cm": int(round(sg["w"] * 100))} for sg in segs}
    marks = {k: [p["mark"] for p in v] for k, v in plan.items()}

    # 1) 계단
    for sid, lst in sorted(find_steps(inp).items()):
        pr = profiles[sid]
        for s0, s1, n in lst:
            up = height_at(pr, s1) >= height_at(pr, s0)
            r = (1 if up else -1) * RISER
            tread = (s1 - s0) / n
            rel = [(s0, 0.0)]
            for i in range(n):
                x = s0 + (i + 0.5) * tread
                rel += [(x, i * r), (x, (i + 1) * r)]
            rel.append((s1, n * r))
            _edit(pr, s0, s1, rel)
            # 구간 전체가 계단이면 끝 높이에 맞춰 칸 높이가 늘어나므로, 적는 높이는 실제 단면에서 잰다
            real = abs(height_at(pr, s1) - height_at(pr, s0))
            feats[sid]["steps"].append({"s0": round(s0, 3), "s1": round(s1, 3), "count": n, "rise_m": round(real, 4), "src": "OSM"})

    def steps_of(sid):
        return feats[sid]["steps"]

    # 2) 경계 앞뒤 경사(4.5~5.0°에서 5곳, 5.5~5.9°에서 5곳). 고리 구간은 표시값과 s가 뒤집혀 빼고 고른다
    cand = [sg for sg in segs if not sg["inc"] and not steps_of(sg["id"]) and sg["len"] >= 30 and not is_loop(sg)]
    rng.shuffle(cand)
    boundary_segs = set()
    targets = [rng.uniform(4.6, 4.9) for _ in range(5)] + [rng.uniform(5.6, 5.8) for _ in range(5)]
    for sg, th in zip(cand, targets):
        ms = [m for m in marks[sg["id"]] if 3 <= m <= sg["len"] - 3]
        if not ms:
            continue
        m = rng.choice(ms)
        pr = profiles[sg["id"]]
        sgn = 1 if long_deg(pr, m) >= 0 else -1
        _edit(pr, m - 1.5, m + 1.5, [(m - 1.5, 0.0), (m + 1.5, sgn * 3 * math.tan(math.radians(th)))])
        boundary_segs.add(sg["id"])

    # 3) 턱: 계획 지점과 '더 재는 지점'(3.0° 이상이면 생긴다고 넉넉히 보고) 모두에서 떨어뜨린다. 위치는 설계도 s
    E = _evening()
    pseg = {s["seg"]: s for s in inp.pack["segs"]}
    avoid = {}
    for sg in segs:
        pts = plan[sg["id"]]
        pr = profiles[sg["id"]]
        sgn = -1 if is_loop(sg) else 1
        longs = [sgn * long_deg(pr, to_world(sg, p["mark"])) for p in pts]
        boosted = [v + (0.2 if v >= 0 else -0.2) for v in longs]
        more = more_points(E, pseg[sg["id"]], pts, boosted, rules)
        avoid[sg["id"]] = [to_world(sg, p["mark"]) for p in pts + more]
    shapes = ["square", "chamfer", "smooth"]
    bump_segs = [sg for sg in segs if sg["len"] >= 10 and sg["id"] not in boundary_segs]
    rng.shuffle(bump_segs)
    n_rand = int(round(0.15 * len(segs)))
    sizes = [rng.randint(12, 14) for _ in range(3)] + [rng.randint(18, 22) for _ in range(5)] + [rng.randint(13, 60) for _ in range(max(0, n_rand - 8))]
    # 11/15 팀 결정: 경계 사례 8개 밖의 높이는 '현실형 섞기'로 바꾼다. 다른 가상 값이 따라 바뀌지 않게
    # 위 뽑기는 그대로 두고(rng 순서 유지) 높이만 따로 뽑은 값으로 바꾼다.
    sizes[8:] = realistic_bumps(len(sizes) - 8, seed)

    def ok_spot(sg, s, half):
        return (all(abs(m - s) > half + 0.6 for m in avoid[sg["id"]]) and not _in_span(steps_of(sg["id"]), s, 0.5 + half)
                and all(abs(v - s) >= 1.5 + half for v in sharp_corners(sg)))

    def put_bump(pr, s, half, dz, run_mm):
        if run_mm == 0:
            _edit(pr, s, s, [(s, 0.0), (s, dz)])
            return
        # 턱 구간 안에서도 바로 앞 경사를 유지한다(경사선 사이 높이 차 = 턱 높이).
        # 턱을 넣으면 나머지 경사가 조금 바뀌므로, 넣은 뒤의 앞 경사로 몇 번 다시 맞춘다
        a = s - half - 0.02
        s0, h0 = pr.s.copy(), pr.h.copy()
        g = (height_at(pr, a) - height_at(pr, a - 0.3)) / 0.3
        for _ in range(5):
            pr.s, pr.h = s0.copy(), h0.copy()
            _edit(pr, s - half, s + half, [(s - half, 0.0), (s + half, dz + g * 2 * half)])
            g2 = (height_at(pr, a) - height_at(pr, a - 0.3)) / 0.3
            if abs(g2 - g) < 1e-7:
                break
            g = g2

    def clear_after(sg, pr, s, half):
        # 턱을 넣으면 양 끝 높이를 지키려고 나머지 경사가 (턱 높이 / 구간 길이)만큼 바뀐다. 큰 턱은 0.2° 여유를 넘어
        # 넣기 전에는 없던 '더 재는 지점'을 턱 옆에 만들 수 있으므로, 넣은 뒤의 실제 경사로 다시 본다(11/15).
        pts = plan[sg["id"]]
        sgn = -1 if is_loop(sg) else 1
        longs = [sgn * long_deg(pr, to_world(sg, p["mark"])) for p in pts]
        boosted = [v + (0.2 if v >= 0 else -0.2) for v in longs]
        more = more_points(E, pseg[sg["id"]], pts, boosted, rules)
        return all(abs(to_world(sg, p["mark"]) - s) > half + 0.6 for p in pts + more)

    rmove = random.Random(seed + 2000)  # 겹쳐서 옮길 자리는 따로 뽑는다(다른 가상 값의 뽑기 순서 유지)
    k = 0
    for sg in bump_segs:
        if k >= len(sizes):
            break
        mm = sizes[k]
        shape = shapes[k % 3]
        run_mm = {"square": 0, "chamfer": 2 * mm, "smooth": rules["bump"]["smooth_ratio"] * mm}[shape]
        half = run_mm / 2000
        L = sg["len"]
        for _ in range(60):
            s = round(rng.uniform(1.0 + half, L - 1.0 - half), 2)
            if ok_spot(sg, s, half):
                break
        else:
            continue
        up = rng.random() < 0.5
        dz = (1 if up else -1) * mm / 1000
        pr = profiles[sg["id"]]
        keep = (pr.s.copy(), pr.h.copy())
        placed = False
        for t in range(61):
            if t > 0:
                s = round(rmove.uniform(1.0 + half, L - 1.0 - half), 2)
                if not ok_spot(sg, s, half):
                    continue
            put_bump(pr, s, half, dz, run_mm)
            if clear_after(sg, pr, s, half):
                placed = True
                break
            pr.s, pr.h = keep[0].copy(), keep[1].copy()
        if not placed:
            continue
        feats[sg["id"]]["bumps"].append({"s": s, "mm": mm, "dir": "up" if up else "down", "shape": shape, "run_mm": run_mm, "src": "가상"})
        k += 1

    # 4) 좌우 기울기
    def add_cross(sg, lo, hi, deg):
        st = steps_of(sg["id"])
        if any(not (hi <= x["s0"] or lo >= x["s1"]) for x in st):
            return False
        if any(not (hi <= v - 1.2 or lo >= v + 1.2) for v in sharp_corners(sg)):
            return False
        # 토막 끝(구간 끝 제외)은 측정 지점에서 1.6 m 넘게: 기운 띠와 평평한 띠 사이 비틀린 면이 지점의 1 m 창에 들지 않게
        for e in (lo, hi):
            if 1e-6 < e < sg["len"] - 1e-6 and any(abs(e - m) < 1.6 for m in avoid[sg["id"]]):
                return False
        feats[sg["id"]]["cross"].append({"s0": round(lo, 3), "s1": round(hi, 3), "deg": round(deg, 2), "low": rng.choice(["left", "right"]), "src": "가상"})
        return True

    order = segs[:]
    rng.shuffle(order)
    nb = 0
    for sg in order:  # 경계 사례 2.0~2.5°: 계획 지점을 덮게 6곳(고리 구간 제외)
        if nb >= 6:
            break
        if is_loop(sg):
            continue
        ms = [m for m in marks[sg["id"]] if not _in_span(steps_of(sg["id"]), m, 0.6)]
        if not ms:
            continue
        m = rng.choice(ms)
        if add_cross(sg, max(0.0, m - 2), min(sg["len"], m + 2), rng.uniform(2.05, 2.45)):
            nb += 1
    for sg in order:
        if feats[sg["id"]]["cross"] or sg["len"] < 3:
            continue
        u = rng.random()
        if u < 0.30:
            deg = rng.uniform(0.5, 1.8)
        elif u < 0.38:
            deg = rng.uniform(2.6, 4.5)
        else:
            continue
        for _ in range(10):  # 지점·꺾임을 피하는 자리를 몇 번 찾아본다
            span = min(sg["len"], rng.uniform(3, 15))
            lo = rng.uniform(0, sg["len"] - span)
            if add_cross(sg, lo, lo + span, deg):
                break

    # 5) 노면
    tagged, nogo = {}, set()
    for sid, p, ln in _net_edges(inp):
        if p.get("osm") == NOGO_WAY:
            nogo.add(sid)
        if p.get("surface") in OSM_MAT:
            t = tagged.setdefault(sid, {})
            t[OSM_MAT[p["surface"]]] = t.get(OSM_MAT[p["surface"]], 0) + ln
    free = []
    for sg in segs:
        sid, L = sg["id"], sg["len"]
        if sid in nogo:
            feats[sid]["surf"] = [{"s0": 0.0, "s1": L, "material": "gravel", "grade": "very_bad", "src": "OSM", "reason": "OSM wheelchair=no"}]
            continue
        if sid in tagged:
            mat = max(sorted(tagged[sid]), key=lambda k: tagged[sid][k])
            g = _grade(rng, mat)
            feats[sid]["surf"] = [{"s0": 0.0, "s1": L, "material": mat, "grade": g, "src": "OSM", "reason": "가상 등급" if g == "very_bad" else ""}]
            continue
        if sg["road"]:
            pool = ["asphalt", "concrete"]
        elif sg["drawn"]:
            pool = ["soil", "stone", "songi", "grass", "gravel"]
        else:
            pool = ["block", "slab", "concrete", "deck", "rubber", "coir", "other"]
        parts = 1 if L < 10 else rng.randint(1, 2 if L < 40 else 3)
        cuts = sorted(rng.uniform(0.2, 0.8) * L for _ in range(parts - 1))
        edges = [0.0] + [round(c, 3) for c in cuts] + [L]
        for a, b in zip(edges, edges[1:]):
            mat = rng.choice(pool)
            x = {"s0": a, "s1": b, "material": mat, "grade": _grade(rng, mat), "src": "가상", "reason": ""}
            feats[sid]["surf"].append(x)
            free.append(x)
    for x in free:
        if x["grade"] == "very_bad":
            x["reason"] = "가상"

    def fill(key, values):
        for v in values:
            while sum(x[key] == v for f in feats.values() for x in f["surf"]) < 2:
                donors = [x for x in free if sum(y[key] == x[key] for f in feats.values() for y in f["surf"]) > 3]
                d = rng.choice(donors)
                d[key] = v
                if key == "material":
                    d["grade"] = _grade(rng, v)
                d["reason"] = "가상" if d["grade"] == "very_bad" else ""

    fill("material", MATERIALS)
    fill("grade", GRADES)

    # 6) 땅을 길 높이에 맞춰 다시 만든다. 계단·경사 태그 때문에 길 높이가 원래 땅과 몇 m 다를 수 있어,
    #    (길 높이 − 땅 높이)를 길 사이 공간에 부드럽게 퍼뜨려 땅에 더한다(도랑·벽이 생기지 않게).
    #    길 가장자리 1 m 안은 길 높이 − 0.02 m, 그 밖 4 m는 길 높이에서 새 땅으로 서서히 바뀐다.
    pts, hs, half = [], [], []
    for sg in segs:
        pr = profiles[sg["id"]]
        for s, h in zip(pr.s, pr.h):
            pts.append(point_at(sg, s)[0])
            hs.append(h)
            half.append(sg["w"] / 2)
    pts, hs, half = np.array(pts), np.array(hs), np.array(half)
    dev = hs - np.array([ter.height(*p) for p in pts])
    key = np.round(pts * 2) / 2  # 0.5 m 칸으로 묶어 같은 자리 점을 평균(Qhull이 겹친 점에 약함)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.ravel()
    udev = np.bincount(inv, dev) / np.bincount(inv)
    ax = ter.origin + np.arange(ter.n) * ter.cell
    X, Z = np.meshgrid(ax, ax)
    grid = np.c_[X.ravel(), Z.ravel()]
    D = griddata(uniq, udev, grid, method="linear")
    far = np.isnan(D)
    D[far] = griddata(uniq, udev, grid[far], method="nearest")
    D = gaussian_filter(D.reshape(ter.n, ter.n), sigma=2.0).ravel()
    newh = ter.h.ravel() + D
    tree = cKDTree(pts)
    dist, idx = tree.query(grid, distance_upper_bound=float(half.max()) + 5.0)
    ok = np.isfinite(dist)
    edge = np.full(len(grid), np.inf)
    edge[ok] = dist[ok] - half[idx[ok]]  # 길 가장자리에서 잰 거리
    near = ok & (edge <= 1.0)
    blend = ok & (edge > 1.0) & (edge < 5.0)
    newh[near] = hs[idx[near]] - 0.02
    u = (edge[blend] - 1.0) / 4.0
    newh[blend] = (hs[idx[blend]] - 0.02) * (1 - u) + newh[blend] * u
    ter.h = newh.reshape(ter.n, ter.n)
    _press_under_paths(ter, segs, profiles, feats)
    return feats


def _points_along(seg, xs):
    """구간 선 위 여러 s의 (x, z)와 진행 방향(배열 판 point_at)."""
    pts = seg_points(seg)
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
    t = np.clip(xs / seg["len"], 0, 1) * d[-1]
    i = np.clip(np.searchsorted(d, t, side="right") - 1, 0, len(pts) - 2)
    seglen = np.maximum(d[i + 1] - d[i], 1e-9)
    u = ((t - d[i]) / seglen)[:, None]
    v = pts[i + 1] - pts[i]
    return pts[i] + v * u, v / seglen[:, None]


def _press_under_paths(ter, segs, profiles, feats):
    """길 표면(좌우 기울기 포함) − 0.02 m보다 높은 땅 격자점을 누른다. 나란한 두 길의 높이가 다르면
    가까운 길 높이를 받은 땅이 다른 길 가장자리를 덮기 때문(묻히는 것보다 떠 보이는 편이 낫다)."""
    flat = ter.h.ravel().copy()
    n = ter.n
    for sg in segs:
        pr = profiles[sg["id"]]
        L = sg["len"]
        xs = np.minimum(np.arange(0.0, L + 0.25, 0.25), L)
        P, D = _points_along(sg, xs)
        left = np.c_[-D[:, 1], D[:, 0]]
        h = np.minimum.reduce([np.interp(np.clip(xs + k, 0, L), pr.s, pr.h) for k in (-0.13, 0.0, 0.13)])
        tan = np.zeros_like(xs)
        for c in feats[sg["id"]]["cross"]:
            m = (xs >= c["s0"] - 0.13) & (xs <= c["s1"] + 0.13)
            tan[m] = math.tan(math.radians(c["deg"]))
        for o in np.linspace(-sg["w"] / 2 - 0.1, sg["w"] / 2 + 0.1, 9):
            q = P + left * o
            surf = h - np.abs(o) * tan - 0.02  # 기운 쪽이 어느 쪽이든 낮은 쪽 높이로 넉넉히
            fx = np.clip((q[:, 0] - ter.origin) / ter.cell, 0, n - 1.000001)
            fz = np.clip((q[:, 1] - ter.origin) / ter.cell, 0, n - 1.000001)
            ix, iz = fx.astype(int), fz.astype(int)
            for jz, jx in ((iz, ix), (iz, ix + 1), (iz + 1, ix), (iz + 1, ix + 1)):
                np.minimum.at(flat, jz * n + jx, surf)
    ter.h = flat.reshape(n, n)


# ---------------------------------------------------------------------------
# 설계도 JSON과, JSON에서 값을 읽는 함수(가상 기록·시험·Unity 확인이 같이 쓴다)
# ---------------------------------------------------------------------------
def build_world(inp: Inputs, seed: int) -> dict:
    ter = make_terrain(inp.size_m, seed)
    steps = find_steps(inp)
    nodes = node_heights(inp, ter, _stair_drops(inp, ter, steps))
    profiles = make_profiles(inp, ter, nodes)
    plan = plan_points(inp)
    feats = add_features(inp, ter, profiles, plan, seed)
    here = str(pathlib.Path(__file__).resolve().parent)
    if here not in sys.path:  # python -I로 돌리면 같은 폴더 모듈을 자동으로 못 찾는다
        sys.path.insert(0, here)
    import virtual_extras  # 평면으로만 보이던 것(빠진 건물·돌담·울타리·연못), 연못은 땅도 낮춘다
    extras = virtual_extras.build_extras(inp, ter, seed)
    segs = []
    for sg in sorted(inp.segs, key=lambda x: x["id"]):
        pr, f = profiles[sg["id"]], feats[sg["id"]]
        prof = [v for s, h in zip(pr.s, pr.h) for v in (round(float(s), 3), round(float(h), 4))]
        segs.append({"id": sg["id"], "a": sg["a"], "b": sg["b"], "len": sg["len"], "w": sg["w"], "width_cm": f["width_cm"],
                     "prof": prof, "cross": f["cross"], "bumps": f["bumps"], "steps": f["steps"], "surf": f["surf"]})
    import virtual_obstacles  # 2·3차 항목(장애물 16종·시설 7종, 가상). 길 옆 낙차는 땅도 낮춘다
    extras.update(virtual_obstacles.build_obstacles(inp, ter, segs, seed))
    return {
        "version": 1, "virtual": True, "seed": seed, "built": datetime.now().astimezone().isoformat(timespec="seconds"),
        "pack": inp.pack["hash"], "net": inp.pack["net"],
        "terrain": {"n": ter.n, "cell": ter.cell, "origin": round(ter.origin, 3), "h": [round(float(v), 3) for v in ter.h.ravel()]},
        "segs": segs, **extras,
    }


def write_world(world: dict, path):
    pathlib.Path(path).write_text(json.dumps(world, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def seg_profile(seg: dict) -> Profile:
    p = np.array(seg["prof"], float).reshape(-1, 2)
    return Profile(s=p[:, 0], h=p[:, 1])


def in_steps(seg: dict, s: float) -> bool:
    return _in_span(seg["steps"], s)


def long_at(seg: dict, s: float) -> float:
    """설계도 구간의 앞뒤 경사 정답(°). 계단 안은 계단 전체 기울기, 계단 옆이면 1 m 창을 계단 밖으로 민다."""
    pr = seg_profile(seg)
    L = seg["len"]
    for st in seg["steps"]:
        if st["s0"] <= s <= st["s1"]:
            return math.degrees(math.atan((height_at(pr, st["s1"]) - height_at(pr, st["s0"])) / max(st["s1"] - st["s0"], 1e-9)))
    a, b = s - 0.5, s + 0.5
    for st in seg["steps"]:
        if a < st["s1"] and b > st["s0"]:
            a, b = (st["s1"], min(L, st["s1"] + 1.0)) if s > st["s1"] else (max(0.0, st["s0"] - 1.0), st["s0"])
    if a < 0:
        a, b = 0.0, min(1.0, L)
    if b > L:
        a, b = max(0.0, L - 1.0), L
    if b - a < 1e-9:
        return 0.0
    return math.degrees(math.atan((height_at(pr, b) - height_at(pr, a)) / (b - a)))


def cross_deg(seg: dict, s: float) -> float:
    for c in seg["cross"]:
        if c["s0"] <= s <= c["s1"]:
            return float(c["deg"])
    return 0.0


def check_world(world: dict, plan: dict) -> list:
    """설계도 조건 검사(시험과 CLI가 같이 쓴다). 문제 문장 목록, 없으면 [].
    계단 밖 계획 지점의 앞뒤 |경사| < 15°, 좌우 0~10°, 턱 0~300 mm, 경계 사례 개수."""
    out, longs, crosses = [], [], []
    for s in world["segs"]:
        for p in plan.get(s["id"], []):
            x = to_world(s, p["mark"])
            if in_steps(s, x):
                continue
            v, c = long_at(s, x), cross_deg(s, x)
            longs.append(v)
            crosses.append(c)
            if abs(v) >= 15:
                out.append(f"앞뒤 {v:.1f}°: 구간 {s['id']} 표시값 {p['mark']}")
            if not 0 <= c < 10:
                out.append(f"좌우 {c:.1f}°: 구간 {s['id']} 표시값 {p['mark']}")
        out += [f"턱 {b['mm']} mm: 구간 {s['id']}" for b in s["bumps"] if not 0 < b["mm"] <= 300]
    bumps = [b["mm"] for s in world["segs"] for b in s["bumps"]]
    for name, cnt, need in (("앞뒤 4.5~5.0°", sum(4.5 <= abs(v) <= 5.0 for v in longs), 5),
                            ("앞뒤 5.5~5.9°", sum(5.5 <= abs(v) <= 5.9 for v in longs), 5),
                            ("좌우 2.0~2.5°", sum(2.0 <= c <= 2.5 for c in crosses), 5),
                            ("턱 12~14 mm", sum(12 <= b <= 14 for b in bumps), 3),
                            ("턱 18~22 mm", sum(18 <= b <= 22 for b in bumps), 5)):
        if cnt < need:
            out.append(f"경계 사례 {name} {cnt}곳(필요 {need})")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True)
    ap.add_argument("--pack", required=True)
    ap.add_argument("--net", required=True)
    ap.add_argument("--osm", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    inp = load_inputs(a.map, a.pack, a.net, a.osm)
    w = build_world(inp, a.seed)
    probs = check_world(w, plan_points(inp))
    if probs:  # 다른 씨앗에서 조건을 어기면 쓰지 않고 멈춘다
        print(f"씨앗 {a.seed}의 설계도가 조건을 어겨 쓰지 않음({len(probs)}건):")
        print("\n".join(probs[:10]))
        raise SystemExit(1)
    write_world(w, a.out)
    S = w["segs"]
    mats = {x["material"] for s in S for x in s["surf"]}
    print(f"구간 {len(S)}, 계단 {sum(len(s['steps']) for s in S)}곳, 턱 {sum(len(s['bumps']) for s in S)}개, "
          f"좌우 토막 {sum(len(s['cross']) for s in S)}개, 노면 토막 {sum(len(s['surf']) for s in S)}개 재질 {len(mats)}종, "
          f"땅 {w['terrain']['n']}x{w['terrain']['n']} -> {a.out}")


if __name__ == "__main__":
    main()
