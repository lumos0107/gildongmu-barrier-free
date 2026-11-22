"""제주대 Unity 맵 자료(jejunu1000_map.json)와 바닥 사진을 만든다(계획 Task 7).

칸은 export_minsokchon.py와 같다(site, name, pack, net, mpp, sizeM, start, startNode, boundary, segs, steps, buildings, trees)
+ walls(옹벽·석축). segs에는 kind, surf_src, kerbs, width_src를 더한다.
좌표: pack과 같은 18단계 항공사진 가운데 원점(x 동쪽 m, z 북쪽 m). 바닥 사진은 같은 범위의 19단계(aerial_z19_full.jpg).

사용: python -I DataPrep/jejunu/export_map.py --pack <jejunu1000 pack> [--out DataPrep/jejunu/out]
"""
import argparse
import json
import math
import pathlib
import random
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from shapely import STRtree  # noqa: E402
from shapely.geometry import LineString, Point  # noqa: E402

import common  # noqa: E402
import net_graph as NG  # noqa: E402
from common import OUT, SITE_DIR, attr_float, campus_zone, load_1000, load_geo, new_buildings, shape_of  # noqa: E402
from net_parts import building_name  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
DEFAULT_W = {"sidewalk": 2.0, "road_campus": 5.0, "road_public": 5.0, "drawn": 1.8}


def flat(pts):
    return [round(float(v), 2) for p in pts for v in p]


# export_minsokchon.py와 같은 삼각형 나누기(그 파일은 불러오면 바로 실행돼서 옮겨 적음)
def area2(ring):
    return sum(ring[i - 1][0] * ring[i][1] - ring[i][0] * ring[i - 1][1] for i in range(len(ring)))


def ear_clip(ring):
    idx = list(range(len(ring)))
    tris = []

    def convex(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) > 1e-9

    def in_tri(p, a, b, c):
        d1 = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        d2 = (c[0] - b[0]) * (p[1] - b[1]) - (c[1] - b[1]) * (p[0] - b[0])
        d3 = (a[0] - c[0]) * (p[1] - c[1]) - (a[1] - c[1]) * (p[0] - c[0])
        return d1 >= 0 and d2 >= 0 and d3 >= 0
    guard = 0
    while len(idx) > 3 and guard < 5000:
        guard += 1
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = ring[i0], ring[i1], ring[i2]
            if not convex(a, b, c):
                continue
            if any(in_tri(ring[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            tris += [i0, i1, i2]
            idx.pop(k)
            break
        else:
            break
    for k in range(1, len(idx) - 1):
        tris += [idx[0], idx[k], idx[k + 1]]
    return tris


def seg_line(seg, geo):
    xy = seg["xy"]
    return LineString([geo.to5186(*geo.lonlat(xy[i], xy[i + 1])) for i in range(0, len(xy), 2)])


def attach(seg_ln, seg_len, net_parts, tree=None) -> list:
    """연결망 선 가운데 구간 선 위(0.6 m 안)에 놓인 것의 s 범위. [{s0, s1, props}], 0~seg_len을 빈틈없이 덮는다."""
    tree = tree or STRtree([p["geom"] for p in net_parts])
    buf = seg_ln.buffer(0.6)
    k = seg_len / max(seg_ln.length, 1e-9)
    got = []
    for j in tree.query(buf):
        g = net_parts[j]["geom"]
        if g.length < 1e-6 or g.difference(buf).length > 0.05 * g.length + 0.05:
            continue
        a, b = sorted((seg_ln.project(Point(g.coords[0])) * k, seg_ln.project(Point(g.coords[-1])) * k))
        if b - a > 1e-3:
            got.append([a, b, net_parts[j]["props"]])
    if not got:
        m = seg_ln.interpolate(0.5, normalized=True)
        j = min(tree.query(m.buffer(5.0)), key=lambda i: net_parts[i]["geom"].distance(m), default=None)
        props = net_parts[j]["props"] if j is not None else {"kind": "drawn", "surface": "other", "src": "가상"}
        return [{"s0": 0.0, "s1": seg_len, "props": props}]
    got.sort(key=lambda x: x[0])
    out = []
    for a, b, p in got:
        if out and a < out[-1]["s1"]:
            a = out[-1]["s1"]
        if b - a <= 1e-3:
            continue
        if out and a > out[-1]["s1"]:
            out[-1]["s1"] = a  # 빈틈은 앞 토막을 늘려 메운다
        out.append({"s0": a, "s1": b, "props": p})
    out[0]["s0"] = 0.0
    out[-1]["s1"] = seg_len
    return [{"s0": round(x["s0"], 3), "s1": round(x["s1"], 3), "props": x["props"]} for x in out]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    out_dir = pathlib.Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    pack = json.loads(pathlib.Path(a.pack).read_text(encoding="utf-8"))
    pack.pop("aerial", None)
    geo = load_geo()
    assert pack["map"]["origin"] == [geo.ox, geo.oy] and pack["map"]["zoom"] == geo.zoom, "pack과 항공사진 기준이 다름"
    U = lambda x, y: geo.unity(*geo.px_from5186(x, y))  # noqa: E731
    feats = load_1000()
    zone = campus_zone()
    net = NG.load_parts(SITE_DIR / "network.geojson")
    tree = STRtree([p["geom"] for p in net])
    kerbs = [(Point(common.Geo.to5186(*f["geometry"]["coordinates"])), f["properties"])
             for f in json.loads((SITE_DIR / "kerbs.geojson").read_text(encoding="utf-8"))["features"]]

    # 길 ------------------------------------------------------------------
    segs, lines = [], {}
    for s in pack["segs"]:
        ln = seg_line(s, geo)
        lines[s["seg"]] = ln
        spans = attach(ln, s["len"], net, tree)
        main = max(spans, key=lambda x: x["s1"] - x["s0"])["props"]
        kind = main.get("kind", "drawn")
        w = float(main.get("width") or DEFAULT_W.get(kind, 2.0))
        w = min(max(w, 1.0), 12.0)
        segs.append({"id": s["seg"], "a": s["a"], "b": s["b"], "road": s["road"], "drawn": s["drawn"] > 0, "len": s["len"], "inc": [],
                     "w": round(w, 2), "p": flat(geo.unity(s["xy"][i], s["xy"][i + 1]) for i in range(0, len(s["xy"]), 2)),
                     "kind": kind, "width_src": main.get("width_src") or main.get("src", "가상"),
                     "surf_src": [{"s0": x["s0"], "s1": x["s1"], "surface": x["props"].get("surface", "other"),
                                   "src": x["props"].get("surface_src") or x["props"].get("src", "가상"),
                                   "kind": x["props"].get("kind", "")} for x in spans], "kerbs": []})
    by = {s["id"]: s for s in segs}
    # 턱: 건너는 곳·진출입부·잇는 선 구간 가운데 턱 점에서 1 m 안의 것에 둔다(없으면 가장 가까운 구간)
    link_kinds = ("crossing", "driveway", "link", "road_campus", "road_public")
    nk, nk_skip = 0, 0
    for pt, pr in kerbs:
        cand = [(lines[sid].distance(pt), sid) for sid in by if lines[sid].distance(pt) <= 1.0]
        if not cand:
            continue
        def link_near(sid):  # 턱 자리 0.6 m 안에 잇는 선(건너는 곳·진출입부·잇기·차도) 토막이 있는지
            x0 = lines[sid].project(pt) * by[sid]["len"] / max(lines[sid].length, 1e-9)
            return any(sp["kind"] in link_kinds and sp["s0"] - 0.6 <= x0 <= sp["s1"] + 0.6 for sp in by[sid]["surf_src"])
        pref = [c for c in cand if link_near(c[1])]
        if not pref:  # 잇는 선이 지워졌거나 안 붙은 턱 점: 보도 한가운데 놓지 않는다(최종 검토 Important 6)
            nk_skip += 1
            continue
        d, sid = min(pref)
        s = by[sid]
        L = s["len"]
        x = lines[sid].project(pt) * L / max(lines[sid].length, 1e-9)
        if L < 1.6:
            x = L / 2
        elif x < 0.5:
            x = 0.8
        elif x > L - 0.5:
            x = L - 0.8
        if any(abs(k["s"] - x) < 0.5 for k in s["kerbs"]):
            continue

        def kind_at(t):
            for sp in s["surf_src"]:
                if sp["s0"] <= t <= sp["s1"]:
                    return sp["kind"]
            return ""
        before, after = kind_at(max(0.0, x - 0.6)) == "sidewalk", kind_at(min(L, x + 0.6)) == "sidewalk"
        # 구간 방향(a→b)으로 걸을 때 보도로 올라가면 up, 보도에서 내려가면 down
        dr = "up" if (after and not before) else "down" if (before and not after) else ("up" if x >= L / 2 else "down")
        s["kerbs"].append({"s": round(x, 3), "kind": pr["kind"], "src": pr["src"], "dir": dr})
        nk += 1

    # 계단 선(설계도가 vw.find_steps로 구간에 붙임) -----------------------------
    steps = [{"p": flat(U(*c) for c in p["geom"].coords), "src": p["props"].get("src", "1:1000(2011)")} for p in net if p["props"].get("highway") == "steps"]

    # 옹벽·석축 -------------------------------------------------------------
    walls = []
    for f in feats:
        if f["code"] == "F0040000" and f["gtype"] == "L" and attr_float(f, "높이") > 0:
            g = shape_of(f)
            if g.geom_type == "LineString" and g.intersects(zone):
                walls.append({"p": flat(U(*c) for c in g.coords), "h": round(attr_float(f, "높이"), 2), "t": 0.4,
                              "kind": f["attrs"].get("종류", ""), "src": f["src"]})

    # 건물 ---------------------------------------------------------------
    img = np.array(Image.open(SITE_DIR / "aerial_z19.jpg").convert("RGB")).astype(np.float32)
    H, W = img.shape[:2]
    inside = campus_zone(0)
    big = zone.buffer(30)
    raw = []
    for f in feats:
        if f["code"] == "B0010000" and f["gtype"] == "A":
            g = shape_of(f)
            if g.geom_type == "Polygon" and g.centroid.within(big):
                raw.append((g, building_name(f), max(1, int(attr_float(f, "층수", 1) or 1)), f["src"]))
    for g in new_buildings(feats, campus_zone(0)):
        raw.append((g, "", 1, "브이월드"))
    seg_pts = np.array([[s["p"][i], s["p"][i + 1]] for s in segs for i in range(0, len(s["p"]), 2)])
    bmask = np.zeros((H, W), np.uint8)
    buildings = []
    for g, name, floors, src in raw:
        ring_px = [geo.px_from5186(*c) for c in g.exterior.coords][:-1]
        if len(ring_px) < 3:
            continue
        cv2.fillPoly(bmask, [np.array(ring_px, np.int32)], 1)
        m = np.zeros((H, W), np.uint8)
        cv2.fillPoly(m, [np.array(ring_px, np.int32)], 1)
        sel = img[m > 0]
        col = sel.mean(0) if len(sel) else np.array([150, 150, 150], np.float32)
        ring = [geo.unity(x, y) for x, y in ring_px]
        if area2(ring) < 0:
            ring = ring[::-1]
        (cx, cz), (bw, bd), ang0 = cv2.minAreaRect(np.array(ring, np.float32))
        box = cv2.boxPoints(((cx, cz), (bw, bd), ang0))
        e1, e2 = box[1] - box[0], box[2] - box[1]
        long_e = e1 if np.linalg.norm(e1) >= np.linalg.norm(e2) else e2
        ang = math.degrees(math.atan2(long_e[1], long_e[0]))
        near = seg_pts[np.argmin(((seg_pts - [cx, cz]) ** 2).sum(1))]
        n = np.array([-math.sin(math.radians(ang)), math.cos(math.radians(ang))])
        front = 1 if np.dot(near - [cx, cz], n) >= 0 else -1
        buildings.append({"kind": "modern", "name": name, "floors": floors, "inSite": bool(g.centroid.within(inside)),
                          "cx": round(float(cx), 2), "cz": round(float(cz), 2), "w": round(float(max(bw, bd)), 2), "d": round(float(min(bw, bd)), 2),
                          "ang": round(ang, 1), "front": front, "roof": [round(float(c) / 255, 3) for c in col],
                          "ring": flat(ring), "tris": ear_clip(ring), "src": src})

    # 나무: 1:1,000 가로수 + 항공사진 어두운 초록(export_minsokchon과 같은 규칙) ----------
    trees = []
    for f in feats:
        if f["code"] == "D0030000" and f["gtype"] == "P" and Point(f["geom"][0]).within(big):
            trees += [*map(lambda v: round(v, 2), U(*f["geom"][0])), 2.0, 1]
    blur = cv2.GaussianBlur(img, (0, 0), 1.5)
    r, g_, b = blur[..., 0], blur[..., 1], blur[..., 2]
    lum = (r + g_ + b) / 3
    tm = ((g_ - r > 10) & (g_ >= b) & (lum < 78)).astype(np.uint8)
    tm = cv2.morphologyEx(tm, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    keep_out = cv2.dilate(bmask, np.ones((5, 5), np.uint8))
    for s in pack["segs"]:
        w = by[s["seg"]]["w"]
        pts = np.array(list(zip(s["xy"][0::2], s["xy"][1::2])), np.int32)
        cv2.polylines(keep_out, [pts], False, 1, thickness=2 * int((w / 2 + 1.2) / geo.mpp) + 1)
    tm[keep_out > 0] = 0
    zm = np.zeros((H, W), np.uint8)  # 캠퍼스 경계 60 m 안만(사진 가장자리 숲은 Unity를 무겁게만 함)
    cv2.fillPoly(zm, [np.array([geo.px_from5186(*c) for c in big.exterior.coords], np.int32)], 1)
    tm[zm == 0] = 0
    dist = cv2.distanceTransform(tm, cv2.DIST_L2, 5)
    rng = random.Random(7)
    step = 4.5 / geo.mpp
    y = step / 2
    while y < H:
        x = step / 2
        while x < W:
            tx, ty = int(x + rng.uniform(-0.35, 0.35) * step), int(y + rng.uniform(-0.35, 0.35) * step)
            if 0 <= tx < W and 0 <= ty < H and tm[ty, tx]:
                rad = min(3.6, max(1.5, dist[ty, tx] * geo.mpp + 1.2)) * rng.uniform(0.85, 1.15)
                l = lum[ty, tx]
                trees += [*map(lambda v: round(v, 2), geo.unity(tx, ty)), round(float(rad), 2), 0 if l < 58 else (1 if l < 68 else 2)]
            x += step
        y += step

    sx, sy = pack["start"]
    res = {"site": "jejunu1000", "name": pack["name"], "pack": pack.get("hash"), "net": pack.get("net"),
           "mpp": geo.mpp, "sizeM": round(geo.size_m, 2), "start": list(geo.unity(sx, sy)), "startNode": pack["start_node"],
           "boundary": flat(U(*c) for c in campus_zone(0).exterior.coords),
           "segs": segs, "steps": steps, "buildings": buildings, "trees": trees, "walls": walls}
    (out_dir / "jejunu1000_map.json").write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    full = Image.open(SITE_DIR / "aerial_z19_full.jpg").convert("RGB")  # 2:1 아닌 사진을 위아래로 같게 채워 정사각으로(가운데 원점 그대로)
    sq = Image.new("RGB", (full.width, full.width), (0, 0, 0))
    sq.paste(full, (0, (full.width - full.height) // 2))
    sq.save(out_dir / "aerial.jpg", quality=90)
    kinds = {}
    for s in segs:
        kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
    print(f"길 {len(segs)}구간 {kinds}, 턱 {nk}개(잇는 선 없어 뺀 {nk_skip}), 계단 선 {len(steps)}, 옹벽 {len(walls)}, 건물 {len(buildings)}동"
          f"(브이월드 {sum(1 for b in buildings if b['src'] == '브이월드')}), 나무 {len(trees) // 4}그루 -> {out_dir}")


if __name__ == "__main__":
    main()
