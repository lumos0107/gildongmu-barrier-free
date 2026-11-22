"""재료 선을 잇고 갈림길에서 잘라 측정앱 연결망 형식으로 쓴다(설계 6장 나 9)·10)).

network.geojson 칸은 minsokchon/network.geojson과 같다(cls, in, len, block, osm, highway, surface, width) + kind, src.
좌표는 경위도 소수 7자리(측정앱 도구 routing.key7이 이 값으로 마디를 잇는다).
"""
import json
import math

import numpy as np
import shapely
from scipy.spatial import cKDTree
from shapely import STRtree
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import nearest_points

import common
from common import campus_zone

SNAP_M = 1.0
MERGE_M = 0.3
COLORS = {"road_public": (255, 255, 255), "road_campus": (230, 230, 230), "path": (255, 200, 120), "sidewalk": (255, 50, 50),
          "steps": (0, 160, 255), "crossing": (255, 0, 255), "driveway": (255, 160, 0), "link": (255, 255, 0),
          "entrance": (0, 255, 120), "drawn": (0, 255, 255)}


def _snap_ends(parts, snap_m):
    geoms = [p["geom"] for p in parts]  # 붙인 결과를 바로 반영한다(두 선이 서로의 끝으로 맞바꿔 붙지 않게)
    tree = STRtree(list(geoms))
    out = []
    for i, p in enumerate(parts):
        cs = list(geoms[i].coords)
        for idx in (0, -1):
            if idx == -1 and p["props"].get("wall_end"):
                continue  # 출입 선의 벽 쪽 끝은 붙이지 않는다
            e = Point(cs[idx])
            best = None
            for j in tree.query(e.buffer(snap_m + 1.0)):
                if j == i:
                    continue
                g = geoms[j]
                d = e.distance(g)
                if d <= snap_m and (best is None or d < best[0]):
                    best = (d, j)
            if best is None or best[0] < 1e-9:
                continue
            g = geoms[best[1]]
            q = nearest_points(e, g)[1]
            for c in (g.coords[0], g.coords[-1]):  # 상대 끝이 가까우면 그 끝으로
                if Point(c).distance(q) <= MERGE_M:
                    q = Point(c)
            cs[idx] = (q.x, q.y)
        if len(cs) >= 2 and LineString(cs).length > 1e-6:
            geoms[i] = LineString(cs)
            out.append({**p, "geom": geoms[i]})
    return out


def _merge_nodes(pieces):
    """0.3 m 안의 끝점을 하나로 모으고, 길이가 0이 된 조각은 버린다."""
    ends = np.array([c for p in pieces for c in (p["geom"].coords[0], p["geom"].coords[-1])])
    if not len(ends):
        return pieces
    tree = cKDTree(ends)
    parent = list(range(len(ends)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b in tree.query_pairs(MERGE_M):
        parent[find(a)] = find(b)
    out = []
    for k, p in enumerate(pieces):
        cs = list(p["geom"].coords)
        cs[0] = tuple(ends[find(2 * k)])
        cs[-1] = tuple(ends[find(2 * k + 1)])
        if cs[0] == cs[-1] and len(cs) <= 3:
            continue
        g = LineString(cs)
        if g.length < 1e-6:
            continue
        out.append({**p, "geom": g})
    return out


def assemble(parts, snap_m=SNAP_M) -> list:
    parts = [p for p in parts if p["props"].get("walk", True) is not False and p["geom"].length > 1e-6]
    if not parts:
        return []
    parts = _snap_ends(parts, snap_m)
    # 다른 선 위(5 cm 안)에 놓인 끝점을 그 선의 꼭짓점으로 넣는다: 가장 가까운 점으로 잡은 끝은 부동소수 오차로
    # 선에서 아주 조금 떨어져 있어 shapely.node가 갈림길로 자르지 못한다(최종 검토 Critical 1)
    ends = [Point(c) for p in parts for c in (p["geom"].coords[0], p["geom"].coords[-1])]
    etree = STRtree(ends)
    for p in parts:
        g = p["geom"]
        own = {g.coords[0], g.coords[-1]}
        near = [ends[j] for j in etree.query(g.buffer(0.05)) if (ends[j].x, ends[j].y) not in own and g.distance(ends[j]) < 0.05]
        if near:
            p["geom"] = shapely.snap(g, shapely.MultiPoint(near), 0.05)
    noded = shapely.node(MultiLineString([p["geom"] for p in parts]))
    pieces = [g for g in noded.geoms if g.length > 1e-6]
    geoms = [p["geom"] for p in parts]
    tree = STRtree(geoms)
    out = []
    for g in pieces:
        m = g.interpolate(0.5, normalized=True)
        cand = [(geoms[j].distance(m), j) for j in tree.query(m.buffer(1e-3))]
        if not cand:
            continue
        d, j = min(cand)
        if d > 1e-3:
            continue
        out.append({"geom": g, "props": dict(parts[j]["props"])})
    return _merge_nodes(out)


def lonlat_lines(parts, geo) -> list:
    out = []
    for p in parts:
        out.append([tuple(round(v, 7) for v in geo.from5186(x, y)) for x, y in p["geom"].coords])
    return out


def load_parts(path) -> list:
    g = json.loads(open(path, encoding="utf-8").read())
    to = common.Geo.to5186
    return [{"geom": LineString([to(*c) for c in f["geometry"]["coordinates"]]), "props": f["properties"]} for f in g["features"]]


def components(parts) -> list:
    key = lambda c: (round(c[0], 2), round(c[1], 2))  # noqa: E731
    idx, parent = {}, []

    def nid(c):
        k = key(c)
        if k not in idx:
            idx[k] = len(parent)
            parent.append(len(parent))
        return idx[k]

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    ab = []
    for p in parts:
        a, b = nid(p["geom"].coords[0]), nid(p["geom"].coords[-1])
        parent[find(a)] = find(b)
        ab.append((a, p["geom"].length))
    L = {}
    for a, ln in ab:
        r = find(a)
        L[r] = L.get(r, 0.0) + ln
    return sorted(L.values(), reverse=True)


_KEEP = ("osm", "highway", "surface", "width", "kind", "src", "footway", "width_src", "surface_src", "wall_end")


def write_network(parts, geo, site_dir, start_xy, name="제주대학교 아라캠퍼스(1:1000)") -> dict:
    inside = campus_zone(0)
    feats, lens = [], {}
    lines = lonlat_lines(parts, geo)
    for p, ll in zip(parts, lines):
        if len(set(ll)) < 2:
            continue
        pr = p["props"]
        cls = "steps" if pr.get("highway") == "steps" else "ok"
        props = {"cls": cls, "in": int(p["geom"].interpolate(0.5, normalized=True).within(inside)), "len": round(p["geom"].length, 1), "block": None}
        props.update({k: pr[k] for k in _KEEP if k in pr and pr[k] not in (None, "")})
        feats.append({"type": "Feature", "properties": props, "geometry": {"type": "LineString", "coordinates": [list(c) for c in ll]}})
        lens[cls] = lens.get(cls, 0.0) + p["geom"].length
    # 출발 마디: start_xy에서 가장 가까운 선 끝
    best = None
    for f, p in zip(feats, parts):
        for c5, cl in ((p["geom"].coords[0], f["geometry"]["coordinates"][0]), (p["geom"].coords[-1], f["geometry"]["coordinates"][-1])):
            d = math.dist(c5, start_xy)
            if best is None or d < best[0]:
                best = (d, cl)
    summary = {"site": name, "start": {"given": "1:1000 버스정류장 제주대학교정문", "lonlat": best[1], "snap_m": round(best[0], 1)},
               "graph": {"선": len(feats)}, "len_all_m": {k: round(v) for k, v in lens.items()}, "blocked_nodes": [], "joins": []}
    (site_dir / "network.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")
    (site_dir / "network_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def check_image(parts, geo_full, aerial_path, out_jpg, extra=None, marks=None, scale=0.5) -> None:
    from PIL import Image, ImageDraw
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(aerial_path).convert("RGB")
    im = im.resize((int(im.width * scale), int(im.height * scale)))
    d = ImageDraw.Draw(im)

    def P(x, y):
        a, b = geo_full.px_from5186(x, y)
        return a * scale, b * scale
    for g, col in (extra or []):
        d.line([P(*c) for c in g.coords], fill=col, width=2)
    for p in parts:
        col = COLORS.get(p["props"].get("kind"), (200, 200, 200))
        d.line([P(*c) for c in p["geom"].coords], fill=col, width=3 if p["props"].get("kind") != "steps" else 5)
    for (x, y), col in (marks or []):
        a, b = P(x, y)
        d.ellipse([a - 6, b - 6, a + 6, b + 6], outline=col, width=2)
    im.save(out_jpg, quality=85)


def traced_parts(path_json, geo_full) -> list:
    """항공사진(19단계 화소)에서 그린 보행로 → Part. osm은 drawn_aerial_<id>(측정앱 도구가 '그린 길'로 침)."""
    d = json.loads(open(path_json, encoding="utf-8").read())
    out = []
    for p in d.get("paths", []):
        xy = p["px"]
        pts = [geo_full.to5186(*geo_full.lonlat(xy[i], xy[i + 1])) for i in range(0, len(xy), 2)]
        if len(pts) < 2:
            continue
        out.append({"geom": LineString(pts), "props": {"kind": "drawn", "highway": "footway", "width": float(p.get("w", 2.0)), "width_src": "가상(폭)",
                    "surface": p.get("surface", "other"), "src": p.get("src", "항공사진"), "osm": f"drawn_aerial_{p['id']}"}})
    return out


def stair_status(stair_parts, net_parts, tol=None) -> list:
    """원래 계단마다 (계단 Part, 양 끝이 다른 선과 같은 마디를 쓰는지 [a, b]). 연결망에 계단 조각이 없으면 [False, False]."""
    key = lambda c: (round(c[0], 2), round(c[1], 2))  # noqa: E731
    deg = {}
    steps_ends = []
    for p in net_parts:
        for c in (p["geom"].coords[0], p["geom"].coords[-1]):
            deg[key(c)] = deg.get(key(c), 0) + 1
    present = {p["props"].get("osm") for p in net_parts if p["props"].get("highway") == "steps"}
    by_osm = {}
    for p in net_parts:
        if p["props"].get("highway") == "steps":
            by_osm.setdefault(p["props"].get("osm"), []).append(p["geom"])
    out = []
    for s in stair_parts:
        osm = s["props"].get("osm")
        if osm not in present:  # 연결망에서 잘려 나간 계단(새 건물 안 등)
            out.append((s, [False, False]))
            continue
        res = []
        for c in (s["geom"].coords[0], s["geom"].coords[-1]):
            # 연결망 안 이 계단 조각들의 끝 가운데 원래 끝에 가장 가까운 것(붙이기로 1 m 안에서 움직였을 수 있음)
            cands = [q for g in by_osm[osm] for q in (g.coords[0], g.coords[-1])]
            q = min(cands, key=lambda t: (t[0] - c[0]) ** 2 + (t[1] - c[1]) ** 2)
            same = sum(1 for g in by_osm[osm] for t in (g.coords[0], g.coords[-1]) if key(t) == key(q))
            res.append(deg.get(key(q), 0) - same >= 1 and ((q[0] - c[0]) ** 2 + (q[1] - c[1]) ** 2) ** 0.5 <= SNAP_M + 0.05)
        out.append((s, res))
    return out


def short_links(stair_parts, other_parts, max_m=3.0) -> list:
    """계단 끝이 다른 선(다른 계단 포함)에서 max_m 안이면 곧은 선으로 잇는다(지도 오차 수준, 출처 '가상')."""
    out = []
    for i, s in enumerate(stair_parts):
        rest = [p["geom"] for p in other_parts] + [t["geom"] for j, t in enumerate(stair_parts) if j != i]
        tree = STRtree(rest)
        for c in (s["geom"].coords[0], s["geom"].coords[-1]):
            e = Point(c)
            cand = [rest[j] for j in tree.query(e.buffer(max_m))]
            if not cand:
                continue
            g = min(cand, key=e.distance)
            d = e.distance(g)
            if SNAP_M < d <= max_m:
                q = nearest_points(e, g)[1]
                out.append({"geom": LineString([e, q]), "props": {"kind": "link", "highway": "footway", "width": s["props"]["width"],
                            "surface": s["props"]["surface"], "src": f"가상(계단 끝 {max_m:g} m 안 잇기)", "osm": f"link_st_{len(out)}"}})
    return out


def prune_stubs(parts, kinds=("drawn", "link"), max_m=3.0) -> list:
    """한쪽 끝이 아무 데도 안 붙은 짧은 자투리(그린 길이 기존 선을 살짝 넘어간 끝 등)를 지운다."""
    parts = list(parts)
    while True:
        deg = {}
        for p in parts:
            for c in (p["geom"].coords[0], p["geom"].coords[-1]):
                k = (round(c[0], 2), round(c[1], 2))
                deg[k] = deg.get(k, 0) + 1
        keep = []
        for p in parts:
            a = deg[(round(p["geom"].coords[0][0], 2), round(p["geom"].coords[0][1], 2))]
            b = deg[(round(p["geom"].coords[-1][0], 2), round(p["geom"].coords[-1][1], 2))]
            if p["props"].get("kind") in kinds and p["geom"].length < max_m and min(a, b) == 1 and max(a, b) >= 2:
                continue
            keep.append(p)
        if len(keep) == len(parts):
            return keep
        parts = keep


def stepfree_reachable(parts, start_xy) -> list:
    """출발점(start_xy에 가장 가까운 끝)에서 계단을 지나지 않고 닿는 선들.
    측정앱 구간처럼 갈림이 없는 마디(이웃 선 2개)를 지나는 선은 한 구간으로 묶고, 계단 조각이 든 구간은 통째로 막는다."""
    key = lambda c: (round(c[0], 2), round(c[1], 2))  # noqa: E731
    ends = [(key(p["geom"].coords[0]), key(p["geom"].coords[-1])) for p in parts]
    deg = {}
    for a, b in ends:
        deg[a] = deg.get(a, 0) + 1
        deg[b] = deg.get(b, 0) + 1
    s0 = min(deg, key=lambda k: (k[0] - start_xy[0]) ** 2 + (k[1] - start_xy[1]) ** 2)
    par = list(range(len(parts)))

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    at = {}
    for i, (a, b) in enumerate(ends):
        at.setdefault(a, []).append(i)
        at.setdefault(b, []).append(i)
    for n, lst in at.items():
        if deg[n] == 2 and n != s0 and len(lst) == 2:
            par[find(lst[0])] = find(lst[1])
    chain_steps = {}
    for i, p in enumerate(parts):
        r = find(i)
        chain_steps[r] = chain_steps.get(r, False) or p["props"].get("highway") == "steps"
    adj = {}
    for i, (a, b) in enumerate(ends):
        if chain_steps[find(i)]:
            continue
        adj.setdefault(a, []).append((b, i))
        adj.setdefault(b, []).append((a, i))
    seen, used, st = {s0}, set(), [s0]
    while st:
        u = st.pop()
        for v, i in adj.get(u, []):
            used.add(i)
            if v not in seen:
                seen.add(v)
                st.append(v)
    return [parts[i] for i in sorted(used)]
