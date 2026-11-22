"""제주대 거리뷰 확인 지점 뽑기(2026-11-21): 정문에서 모든 시설로 가는 길(지금 판정 + 시설 판정, 세 유형 × 세 길)이
지나는 턱(1:1,000 인도 선, 278곳 중)과 가상 연석경사로(8곳)를 모아, 12 m 안에 붙은 것은 한 지점으로 묶는다.

    python -I DataPrep/jejunu/roadview_points.py   → DataPrep/jejunu/out/거리뷰/지점.geojson
    python -I DataPrep/jejunu/roadview_points.py --extra   → 지점_2차.geojson(거리뷰 반영 뒤 새 길이 새로 지나게 된 안 본 턱,
        roadview_effect.py를 먼저 돌린다)
"""
import json
import math
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import route_cost as RC  # noqa: E402
import route_engine as R  # noqa: E402
from legacy_compare import SITES  # noqa: E402

OUT = HERE / "out/거리뷰"
CLUSTER_M = 12.0


def px_to_lonlat(m, x, y):
    n = 256 * 2 ** m["zoom"]
    lon = (x + m["origin"][0]) / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + m["origin"][1]) / n))))
    return lon, lat


def point_on(xy, L, s):
    pts = [(xy[i], xy[i + 1]) for i in range(0, len(xy) - 1, 2)]
    d = [0.0]
    for a, b in zip(pts, pts[1:]):
        d.append(d[-1] + math.dist(a, b))
    t = max(0.0, min(1.0, s / (L or 1.0))) * d[-1]
    for i in range(len(pts) - 1):
        if d[i + 1] >= t:
            u = 0 if d[i + 1] == d[i] else (t - d[i]) / (d[i + 1] - d[i])
            return pts[i][0] + (pts[i + 1][0] - pts[i][0]) * u, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * u
    return pts[-1]


def main(out=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ri, pack, fac, start, _ = SITES["jejunu1000"]
    wt = RC.load_weights(HERE.parent / "route_weights.json")
    pk = json.loads(pathlib.Path(pack).read_text(encoding="utf-8"))
    segs = {s["seg"]: s for s in pk["segs"]}
    used = {}  # 구간 -> [(lo, hi)]
    for fr in (False, True):
        ctx, facs = R.load(ri, pack, fac, facility_rules=fr)
        for f in facs:
            if f["name"] == start:
                continue
            for m in R.MODES:
                rs = [R.route_by_names(ctx, facs, start, f["name"], m)]
                if fr:
                    rs += list(R.route3_by_names(ctx, facs, start, f["name"], m, wt)["routes"].values())
                for r in rs:
                    for st in r["steps"]:
                        used.setdefault(st["seg"], []).append(sorted((st["s0"], st["s1"])))
    rin = json.loads(pathlib.Path(ri).read_text(encoding="utf-8"))
    cand = []
    for x in rin["barriers"]:
        if x["type"] == "bump":
            cand.append(("턱", x["seg"], x["s"], f"턱(가상 높이 {x.get('route_value')} mm)"))
    for x in rin["facilities"]:
        if x["type"] == "curb_ramp":
            cand.append(("연석경사로", x["seg"], x["s"], f"가상 연석경사로 {x.get('slope')}°·끝 턱 {x.get('end_mm')} mm"))
    on = [c for c in cand if any(a - 0.5 <= c[2] <= b + 0.5 for a, b in used.get(c[1], []))]
    pts = []
    for kind, k, s, note in on:
        sg = segs[k]
        x, y = point_on(sg["xy"], sg["len"], s)
        pts.append({"kind": kind, "seg": k, "s": s, "note": note, "x": x, "y": y})
    feats = to_features(pts, pk)
    write(feats, out or OUT / "지점.geojson")
    print(f"후보 턱 {sum(1 for c in cand if c[0] == '턱')}·연석경사로 {sum(1 for c in cand if c[0] != '턱')} → 길 위 {len(on)} → 묶어서 {len(feats)}지점")


def to_features(pts, pk, start_no=1):
    mpp = pk["map"]["mpp"]
    groups = []
    for p in sorted(pts, key=lambda p: (p["kind"] != "연석경사로", p["seg"], p["s"])):
        g = next((g for g in groups if math.dist((g[0]["x"], g[0]["y"]), (p["x"], p["y"])) * mpp <= CLUSTER_M), None)
        (g.append(p) if g else groups.append([p]))
    feats = []
    for i, g in enumerate(groups, start_no):
        cx, cy = sum(p["x"] for p in g) / len(g), sum(p["y"] for p in g) / len(g)
        lon, lat = px_to_lonlat(pk["map"], cx, cy)
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]},
                      "properties": {"no": i, "kinds": sorted({p["kind"] for p in g}), "items": g,
                                     "aerial_px": [round(cx, 1), round(cy, 1)]}})
    return feats


def write(feats, path):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, indent=1), encoding="utf-8")


def extra():
    """2차: 거리뷰 반영 뒤 새 길이 새로 지나게 된 안 본 턱(반영_효과.json의 unchecked_fresh)을 1차 번호 뒤로 이어 붙인다."""
    sys.stdout.reconfigure(encoding="utf-8")
    _, pack, _, _, _ = SITES["jejunu1000"]
    pk = json.loads(pathlib.Path(pack).read_text(encoding="utf-8"))
    segs = {s["seg"]: s for s in pk["segs"]}
    fresh = json.loads((OUT / "반영_효과.json").read_text(encoding="utf-8"))["unchecked_fresh"]
    first = json.loads((OUT / "지점.geojson").read_text(encoding="utf-8"))["features"]
    pts = []
    for u in fresh:
        x, y = point_on(segs[u["seg"]]["xy"], segs[u["seg"]]["len"], u["s"])
        note = f"턱(가상 높이 {u['virtual']} mm)" if u["kind"] == "턱" else f"가상 연석경사로 {u['virtual']}°"
        pts.append({"kind": u["kind"], "seg": u["seg"], "s": u["s"], "note": note, "x": x, "y": y})
    feats = to_features(pts, pk, start_no=max(f["properties"]["no"] for f in first) + 1)
    write(feats, OUT / "지점_2차.geojson")
    print(f"2차 {len(pts)}곳 → 묶어서 {len(feats)}지점(번호 {feats[0]['properties']['no']}~{feats[-1]['properties']['no']})")


if __name__ == "__main__":
    if "--extra" in sys.argv:
        extra()
    else:
        main(sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None)
