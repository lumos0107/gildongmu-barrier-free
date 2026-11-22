"""제주대 설계도(virtual_world.json)를 만든다(설계 6장 다·라, 계획 Task 8).

민속촌 설계도와 같은 형식이다. 다른 점은 이렇다.
- 땅: 공개 지도 땅 높이(terrain.build_terrain)
- 계단 자리·폭: 1:1,000(단 높이 0.15 m는 가상)
- 턱 자리: 맵 자료 kerbs(1:1,000 인도 선 끝·끊김), 높이는 팀 결정 KERB_RULES(가상)
- 노면 재질: 1:1,000·OSM, 그린 길은 가상. 등급은 모두 가상.
- 민속촌처럼 경계 값을 일부러 넣지 않는다(설계 6장 라). 범위 밖 값은 멈추지 않고 목록으로 남긴다.

사용: python -I DataPrep/jejunu/build_world.py --map DataPrep/jejunu/out/jejunu1000_map.json --pack <jejunu1000 pack> --out DataPrep/jejunu/out/virtual_world.json [--seed 7]
"""
import argparse
import copy
import csv
import json
import math
import pathlib
import random
import sys
from datetime import datetime

HERE = pathlib.Path(__file__).resolve().parent
for _p in (HERE, HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import numpy as np  # noqa: E402
from scipy.interpolate import griddata  # noqa: E402
from scipy.ndimage import gaussian_filter  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402

import common  # noqa: E402
import terrain as TR  # noqa: E402
import virtual_world as vw  # noqa: E402
from common import OUT, load_1000, load_geo  # noqa: E402

# 팀 결정 2026-11-15 '현실형 섞기', 같은 날 낮춘 턱을 13~17 mm로 바꿈(경로 엔진은 22 mm 넘으면 막음, 측정앱은 13 mm 이상만 기록)
# (비율, 최소 mm, 최대 mm, 모양)
KERB_RULES = {
    "crosswalk": [(1.0, 13, 17, ["chamfer", "smooth"])],
    "driveway": [(1.0, 13, 17, ["chamfer", "smooth"])],
    "plain": [(0.6, 13, 17, ["chamfer", "smooth"]), (0.4, 100, 150, ["square"])],
}
# 거리뷰 반영(2026-11-22, 설계 Docs/2026-11-22-거리뷰반영-3D맵-설계.md): 거리뷰로 본 턱에 '높이 모름'(unread)과 거리뷰 판정을
# 붙이고(측정 기록에서는 '못 잼'), 엉뚱한 자리의 가상 연석경사로는 뺀다. 3D 턱 높이는 그대로 둔다(바꾸면 길 높이가 바뀌어
# 장애물 난수 순서가 밀리고 출입구 등 거리뷰와 상관없는 가상 값이 다시 뽑힌다).
ROADVIEW_FILES = (OUT / "거리뷰/판정_합본.json", OUT / "거리뷰/판정_2차.json")
ROADVIEW_TOL = 0.06  # 경로입력 s는 표시값 0.1 m 반올림이라 설계도 s와 0.05 m까지 다르다(턱끼리는 1 m 넘게 떨어짐)
ROADVIEW_KEEP_RAMP = ("연석경사로", "모름")
SURF_MAT = {"block": "block", "asphalt": "asphalt", "concrete": "concrete", "unpaved": "soil"}
DRAWN_POOL = (["block"] * 3 + ["concrete"] * 3 + ["asphalt"] * 2 + ["soil", "stone"])
CROSS_KINDS = ("sidewalk", "drawn", "path", "entrance", "link", "driveway")


def load_inputs(map_path, pack_path):
    mp = json.loads(pathlib.Path(map_path).read_text(encoding="utf-8"))
    pack = json.loads(pathlib.Path(pack_path).read_text(encoding="utf-8"))
    pack.pop("aerial", None)
    inp = vw.Inputs(segs=mp["segs"], pack=pack, net={}, osm={}, size_m=float(mp["sizeM"]), steps=mp.get("steps", []),
                    map_data=mp, site_dir=common.SITE_DIR)
    return inp, mp


def _avoid(inp, profiles, plan):
    """계획 지점과 '더 재는 지점'(3.0° 이상이면 생긴다고 넉넉히) 자리. 계획 지점이 없는 짧은 구간은 가운데(가상 기록이 거기서 잼)."""
    E = vw._evening()
    rules = inp.pack["rules"]
    pseg = {s["seg"]: s for s in inp.pack["segs"]}
    out = {}
    for sg in inp.segs:
        pts = plan[sg["id"]]
        pr = profiles[sg["id"]]
        sgn = -1 if vw.is_loop(sg) else 1
        longs = [sgn * vw.long_deg(pr, vw.to_world(sg, p["mark"])) for p in pts]
        boosted = [v + (0.2 if v >= 0 else -0.2) for v in longs]
        more = vw.more_points(E, pseg[sg["id"]], pts, boosted, rules)
        xs = [vw.to_world(sg, p["mark"]) for p in pts + more]
        if not pts:
            xs.append(round(sg["len"] / 2, 1))
        out[sg["id"]] = xs
    return out


def stair_counts(inp, ter, walls=None) -> dict:
    """vw.find_steps의 자리에, 단 수는 땅 높이 차(공개 지도, 옹벽 끊김 포함) / 0.15 m로 센다.
    길이로 센 단 수(한 단 0.35 m)를 넘지 않고 1단 이상. 길이로만 세면 계단 높이가 땅보다 커져 주변 보도 경사가 틀어진다."""
    by = {sg["id"]: sg for sg in inp.segs}
    wl = [(np.array(w["p"], float).reshape(-1, 2), w["h"]) for w in (walls or [])]
    out = {}
    for sid, lst in vw.find_steps(inp).items():
        sg = by[sid]
        for s0, s1, n_len in lst:
            p0, p1 = vw.point_at(sg, s0)[0], vw.point_at(sg, s1)[0]
            dh = abs(ter.height(*p1) - ter.height(*p0))
            mid = (p0 + p1) / 2
            sd = (p1 - p0) / max(np.hypot(*(p1 - p0)), 1e-9)
            near_wall = []
            for q, h in wl:  # 계단 3 m 안에서 계단을 가로지르는(60° 넘게 엇갈린) 옹벽 높이만(옆에 나란한 벽은 빼기, 최종 검토 Minor)
                dd = np.hypot(*(q - mid).T)
                i = int(np.argmin(dd))
                if dd[i] > 3.0:
                    continue
                j = i + 1 if i + 1 < len(q) else i - 1
                wd = (q[j] - q[i]) / max(np.hypot(*(q[j] - q[i])), 1e-9)
                if abs(float(wd @ sd)) < 0.5:
                    near_wall.append(h)
            dh = max([dh] + near_wall)
            out.setdefault(sid, []).append((s0, s1, max(1, min(n_len, int(round(dh / vw.RISER))))))
    return out


def add_steps(inp, profiles, feats, src_by_seg, steps):
    by = {sg["id"]: sg for sg in inp.segs}
    lines = [(np.array(l["p"], float).reshape(-1, 2), l.get("src")) for l in inp.steps]
    for sid, lst in sorted(steps.items()):
        pr = profiles[sid]
        for s0, s1, n in lst:
            mid = vw.point_at(by[sid], (s0 + s1) / 2)[0]
            src0 = min(lines, key=lambda t: np.min(np.hypot(*(t[0] - mid).T)))[1] if lines else None
            up = vw.height_at(pr, s1) >= vw.height_at(pr, s0)
            r = (1 if up else -1) * vw.RISER
            tread = (s1 - s0) / n
            rel = [(s0, 0.0)]
            for i in range(n):
                x = s0 + (i + 0.5) * tread
                rel += [(x, i * r), (x, (i + 1) * r)]
            rel.append((s1, n * r))
            vw._edit(pr, s0, s1, rel)
            real = abs(vw.height_at(pr, s1) - vw.height_at(pr, s0))
            feats[sid]["steps"].append({"s0": round(s0, 3), "s1": round(s1, 3), "count": n, "rise_m": round(real, 4),
                                        "src": f"{src0 or src_by_seg.get(sid, '1:1000(2011)')} 자리·폭, 단 수는 땅 높이 차 / {vw.RISER:g} m(추정)"})


def _pick_kerb(rng, kind):
    bands = KERB_RULES.get(kind, KERB_RULES["plain"])
    u, acc = rng.random(), 0.0
    for share, lo, hi, shapes in bands:
        acc += share
        if u <= acc + 1e-12:
            return rng.randint(lo, hi), rng.choice(shapes)
    share, lo, hi, shapes = bands[-1]
    return rng.randint(lo, hi), rng.choice(shapes)


def load_roadview_points(points) -> list:
    """거리뷰 판정(지점 목록)을 항목 하나씩으로 편다: {kind, seg, s, no, shape, lip, confidence}."""
    return [{"kind": it["kind"], "seg": it["seg"], "s": it["s"], "no": p["no"], "shape": p["shape"],
             "lip": p.get("lip"), "confidence": p.get("confidence")} for p in points for it in p["items"]]


def load_roadview(paths=ROADVIEW_FILES) -> list:
    return load_roadview_points([p for f in paths if pathlib.Path(f).exists()
                                 for p in json.loads(pathlib.Path(f).read_text(encoding="utf-8"))])


def roadview_at(rv, kind, seg, s, tol=ROADVIEW_TOL):
    return next((x for x in rv if x["kind"] == kind and x["seg"] == seg and abs(x["s"] - s) <= tol), None)


def drop_roadview_ramps(facilities, rv):
    """거리뷰에서 연석경사로가 아니라고 본 자리의 연석경사로를 뺀다 → (남긴 것, 뺀 것)."""
    kept, removed = [], []
    for f in facilities:
        j = roadview_at(rv, "연석경사로", f.get("seg"), f.get("s", -1e9)) if f.get("type") == "curb_ramp" else None
        (removed if j and j["shape"] not in ROADVIEW_KEEP_RAMP else kept).append(f)
    return kept, removed


def _put_bump(pr, s, mm, shape, run_mm, up):
    half = run_mm / 2000
    dz = (1 if up else -1) * mm / 1000
    if run_mm == 0:
        vw._edit(pr, s, s, [(s, 0.0), (s, dz)])
        return
    a = s - half - 0.02  # 턱 구간 안에서도 바로 앞 경사를 유지(민속촌 add_features 3)과 같음)
    s0, h0 = pr.s.copy(), pr.h.copy()
    g = (vw.height_at(pr, a) - vw.height_at(pr, a - 0.3)) / 0.3
    for _ in range(5):
        pr.s, pr.h = s0.copy(), h0.copy()
        vw._edit(pr, s - half, s + half, [(s - half, 0.0), (s + half, dz + g * 2 * half)])
        g2 = (vw.height_at(pr, a) - vw.height_at(pr, a - 0.3)) / 0.3
        if abs(g2 - g) < 1e-7:
            break
        g = g2


def add_kerbs(inp, profiles, feats, avoid, rng, rv=()):
    """rv: 거리뷰 항목(load_roadview). 거리뷰로 본 턱에 unread와 roadview를 붙인다(자리·높이는 그대로)."""
    rules = inp.pack["rules"]
    placed, skipped = 0, []
    for sg in sorted(inp.segs, key=lambda x: x["id"]):
        if not sg.get("kerbs"):
            continue
        if vw.is_loop(sg):
            skipped += [(sg["id"], k["s"], "고리 구간") for k in sg["kerbs"]]
            continue
        L = sg["len"]  # 꺾임 옆 피하기는 뺌(3D 검사 때문에 생긴 조건, 사용자 2026-11-15): 측정 지점·계단만 피한다
        for k in sg["kerbs"]:
            mm, shape = _pick_kerb(rng, k["kind"])
            run_mm = {"square": 0, "chamfer": 2 * mm, "smooth": rules["bump"]["smooth_ratio"] * mm}[shape]
            half = run_mm / 2000
            ok_s = None
            for d in [0.0] + [v for k_ in range(1, 11) for v in (0.3 * k_, -0.3 * k_)]:  # ±3 m 안에서 찾음
                s = round(k["s"] + d, 2)
                if not (0.3 + half <= s <= L - 0.3 - half):
                    continue
                if any(abs(m - s) <= half + 0.6 for m in avoid[sg["id"]]):
                    continue
                if vw._in_span(feats[sg["id"]]["steps"], s, 0.5 + half):
                    continue
                if any(abs(b["s"] - s) < 1.0 for b in feats[sg["id"]]["bumps"]):
                    continue
                ok_s = s
                break
            if ok_s is None:
                skipped.append((sg["id"], k["s"], "계획 지점·계단과 겹침"))
                continue
            up = k.get("dir", "up" if ok_s >= L / 2 else "down") == "up"  # 맵 자료가 보도 쪽으로 정한 방향
            j = roadview_at(rv, "턱", sg["id"], ok_s) if rv else None
            extra = {"unread": True, "roadview": {x: j[x] for x in ("no", "shape", "lip", "confidence")}} if j else {}
            _put_bump(profiles[sg["id"]], ok_s, mm, shape, run_mm, up)
            feats[sg["id"]]["bumps"].append({"s": ok_s, "mm": mm, "dir": "up" if up else "down", "shape": shape, "run_mm": run_mm,
                                             "src": f"가상(턱 높이, {k['kind']})", "where_src": k["src"], **extra})
            placed += 1
    return placed, skipped


def add_cross(inp, feats, avoid, rng):
    order = sorted(inp.segs, key=lambda x: x["id"])
    rng.shuffle(order)
    n = 0
    for sg in order:
        if sg.get("kind") not in CROSS_KINDS or sg["len"] < 3 or vw.is_loop(sg):
            continue
        u = rng.random()
        if u < 0.30:
            deg = rng.uniform(0.5, 1.8)
        elif u < 0.38:
            deg = rng.uniform(2.6, 4.5)
        else:
            continue
        for _ in range(10):
            span = min(sg["len"], rng.uniform(3, 15))
            lo = rng.uniform(0, sg["len"] - span)
            hi = lo + span
            if any(not (hi <= x["s0"] or lo >= x["s1"]) for x in feats[sg["id"]]["steps"]):
                continue
            if any(not (hi <= v - 1.2 or lo >= v + 1.2) for v in vw.sharp_corners(sg)):
                continue
            if any(1e-6 < e < sg["len"] - 1e-6 and any(abs(e - m) < 1.6 for m in avoid[sg["id"]]) for e in (lo, hi)):
                continue
            feats[sg["id"]]["cross"].append({"s0": round(lo, 3), "s1": round(hi, 3), "deg": round(deg, 2), "low": rng.choice(["left", "right"]),
                                             "src": "가상"})
            n += 1
            break
    return n


def add_surf(inp, feats, rng):
    for sg in sorted(inp.segs, key=lambda x: x["id"]):
        out = []
        for x in sorted(sg["surf_src"], key=lambda t: t["s0"]):
            mat = SURF_MAT.get(x["surface"])
            src = x["src"]
            if mat is None:
                mat, src = rng.choice(DRAWN_POOL), "가상(재질)"
            if out and (x["s1"] - x["s0"] < 0.5 or out[-1]["material"] == mat):
                out[-1]["s1"] = x["s1"]  # 0.5 m 미만 토막과 같은 재질 토막은 앞 토막에 붙인다
                continue
            out.append({"s0": x["s0"], "s1": x["s1"], "material": mat, "src": src})
        out[0]["s0"], out[-1]["s1"] = 0.0, sg["len"]
        for x in out:
            x["grade"] = vw._grade(rng, x["material"])
            x["grade_src"] = "가상"
            x["reason"] = "가상 등급" if x["grade"] == "very_bad" else ""
            x["s0"], x["s1"] = round(x["s0"], 3), round(x["s1"], 3)
        feats[sg["id"]]["surf"] = out


def spread_and_press(ter, segs, profiles, feats):
    """민속촌 add_features 6)과 같다: (길 높이 − 땅)을 길 사이에 퍼뜨리고 길 아래 땅을 누른다."""
    pts, hs, half = [], [], []
    for sg in segs:
        pr = profiles[sg["id"]]
        for s, h in zip(pr.s, pr.h):
            pts.append(vw.point_at(sg, s)[0])
            hs.append(h)
            half.append(sg["w"] / 2)
    pts, hs, half = np.array(pts), np.array(hs), np.array(half)
    dev = hs - np.array([ter.height(*p) for p in pts])
    key = np.round(pts * 2) / 2
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
    edge[ok] = dist[ok] - half[idx[ok]]
    near = ok & (edge <= 1.0)
    blend = ok & (edge > 1.0) & (edge < 5.0)
    newh[near] = hs[idx[near]] - 0.02
    u = (edge[blend] - 1.0) / 4.0
    newh[blend] = (hs[idx[blend]] - 0.02) * (1 - u) + newh[blend] * u
    ter.h = newh.reshape(ter.n, ter.n)
    vw._press_under_paths(ter, segs, profiles, feats)


def build_world(map_path, pack_path, seed=7, roadview=True) -> dict:
    """roadview가 거짓이면 거리뷰 반영 전(2026-11-15) 설계도와 같다."""
    inp, mp = load_inputs(map_path, pack_path)
    rng = random.Random(seed)
    rv = load_roadview() if roadview else []
    feats1000 = load_1000()
    geo = load_geo()
    ter = TR.build_terrain(feats1000, geo)  # 옹벽 끊김이 있는 땅: 3D 바닥
    ter_s = TR.build_terrain(feats1000, geo, walls=False)  # 매끈한 땅: 길 높이(옹벽 옆을 나란히 가는 길이 끊김을 밟지 않게)
    ter_raw = copy.deepcopy(ter_s)
    # 마디 높이는 공개 지도 땅을 그대로 따른다. 계단 높이를 마디 맞추기에 넣으면, 높이 차가 거의 없는 계단의
    # 오르내림 방향이 제멋대로 정해져 고리에서 부딪히고 마디가 땅에서 최대 9 m까지 끌려갔다. 계단 높이는 구간 안에서만 맞춘다(_edit).
    steps = stair_counts(inp, ter_s)
    nodes = vw.node_heights(inp, ter_s, {})
    profiles = vw.make_profiles(inp, ter_s, nodes)
    plan = vw.plan_points(inp)
    segs = sorted(inp.segs, key=lambda x: x["id"])
    wmax = int(inp.pack["rules"]["width"]["max_cm"])  # 측정앱이 받는 폭 최대값(넓은 차도는 이 값으로 적힌다), 3D 폭 w는 그대로
    feats = {sg["id"]: {"cross": [], "bumps": [], "steps": [], "surf": [], "width_cm": min(int(round(sg["w"] * 100)), wmax)} for sg in segs}
    src_by_seg = {}
    for sg in segs:
        st = [x["src"] for x in sg["surf_src"] if x["src"].startswith("1:1000")]
        src_by_seg[sg["id"]] = st[0] if st else "1:1000"
    add_steps(inp, profiles, feats, src_by_seg, steps)
    avoid = _avoid(inp, profiles, plan)
    n_kerb, kerb_skip = add_kerbs(inp, profiles, feats, avoid, rng, rv)
    n_cross = add_cross(inp, feats, avoid, rng)
    add_surf(inp, feats, rng)
    ter_pre = copy.deepcopy(ter)  # 길 아래 누르기 전 땅: 길 옆 낙차 깊이를 여기서 잰다(최종 검토 Important 2)
    spread_and_press(ter, segs, profiles, feats)
    wsegs = []
    for sg in segs:
        pr, f = profiles[sg["id"]], feats[sg["id"]]
        prof = [v for s, h in zip(pr.s, pr.h) for v in (round(float(s), 3), round(float(h), 4))]
        wsegs.append({"id": sg["id"], "a": sg["a"], "b": sg["b"], "len": sg["len"], "w": sg["w"], "width_cm": f["width_cm"],
                      "width_src": sg.get("width_src", ""), "kind": sg.get("kind", ""),
                      "prof": prof, "cross": f["cross"], "bumps": f["bumps"], "steps": f["steps"], "surf": f["surf"]})
    try:
        import obstacles  # Task 9
        extra = obstacles.build_obstacles(inp, ter, wsegs, seed, mp, ter_pre=ter_pre)
    except ModuleNotFoundError:
        extra = {"obstacles": [], "facilities": []}
    extra["facilities"], ramps_out = drop_roadview_ramps(extra["facilities"], rv)
    world = {"version": 1, "virtual": True, "site": "jejunu1000", "seed": seed, "built": datetime.now().astimezone().isoformat(timespec="seconds"),
             "pack": inp.pack["hash"], "net": inp.pack["net"],
             "note": "땅 높이·계단·턱 자리·노면 재질은 공개 지도(1:1000·1:5000·OSM·항공사진), 턱 높이·좌우·등급·장애물 대부분은 가상. 항목마다 src",
             "terrain": {"n": ter.n, "cell": ter.cell, "origin": round(ter.origin, 3), "h": [round(float(v), 3) for v in ter.h.ravel()]},
             "segs": wsegs, "walls": mp.get("walls", []), "fences": [], "water": [], "buildings_extra": [], **extra}
    world["_report"] = {"kerb_placed": n_kerb, "kerb_skipped": kerb_skip, "cross": n_cross,
                        "roadview_bumps": sum(1 for s in wsegs for b in s["bumps"] if b.get("unread")), "ramps_out": len(ramps_out)}
    _reports(world, mp, ter_raw, plan)
    return world


def _reports(world, mp, ter_raw, plan):
    by = {s["id"]: s for s in mp["segs"]}
    walls = [(np.array(w["p"], float).reshape(-1, 2), w["h"]) for w in mp.get("walls", [])]
    with open(OUT / "계단_높이대조.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["seg", "s0", "s1", "count", "rise_m", "terrain_dh", "wall_h"])
        for s in world["segs"]:
            for st in s["steps"]:
                p0, p1 = vw.point_at(by[s["id"]], st["s0"])[0], vw.point_at(by[s["id"]], st["s1"])[0]
                mid = (p0 + p1) / 2
                wh = max([h for q, h in walls if np.min(np.hypot(*(q - mid).T)) <= 3.0], default=0.0)
                w.writerow([s["id"], st["s0"], st["s1"], st["count"], st["rise_m"], round(abs(ter_raw.height(*p1) - ter_raw.height(*p0)), 3), wh])
    with open(OUT / "범위밖목록.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["seg", "mark", "long_deg", "cross_deg", "kind"])
        for s in world["segs"]:
            for p in plan.get(s["id"], []):
                x = vw.to_world(s, p["mark"])
                if vw.in_steps(s, x):
                    continue
                v, c = vw.long_at(s, x), vw.cross_deg(s, x)
                if abs(v) >= 15 or c >= 10:
                    w.writerow([s["id"], p["mark"], round(v, 2), round(c, 2), s.get("kind", "")])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True)
    ap.add_argument("--pack", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-roadview", action="store_true", help="거리뷰 반영 전(2026-11-15) 설계도")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    w = build_world(a.map, a.pack, a.seed, roadview=not a.no_roadview)
    rep = w.pop("_report")
    pathlib.Path(a.out).write_text(json.dumps(w, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    S = w["segs"]
    n_out = sum(1 for _ in open(OUT / "범위밖목록.csv", encoding="utf-8-sig")) - 1
    print(f"구간 {len(S)}, 계단 {sum(len(s['steps']) for s in S)}곳, 턱 {rep['kerb_placed']}개(못 둔 것 {len(rep['kerb_skipped'])}), "
          f"좌우 토막 {rep['cross']}개, 노면 토막 {sum(len(s['surf']) for s in S)}개, 장애물 {len(w['obstacles'])}, 시설 {len(w['facilities'])}, "
          f"범위 밖 지점 {n_out}개, 땅 {w['terrain']['n']}x{w['terrain']['n']}, "
          f"거리뷰 턱 {rep['roadview_bumps']}개·뺀 연석경사로 {rep['ramps_out']}개 -> {a.out}")


if __name__ == "__main__":
    main()
