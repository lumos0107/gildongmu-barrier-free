"""연결망 재료 선(설계 6장 나). 모두 EPSG:5186, Part = {"geom": LineString, "props": {...}}.

props: kind(road_public·road_campus·path·sidewalk·steps·crossing·driveway·link·entrance·drawn), highway, surface, width, src, osm, (walk)
"""
import math

import numpy as np
import shapely
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import nearest_points, unary_union

import common  # noqa: F401
from common import attr_float, shape_of

ROADS = {"service", "residential", "tertiary", "secondary", "primary", "unclassified"}
PAVE = {"아스팔트": "asphalt", "콘크리트": "concrete", "비포장": "unpaved"}
SW_MAT = {"블록": "block", "아스콘": "asphalt"}
GENERIC_NAMES = {"", "제주대학교", "제주대학교아라캠퍼스"}


def _uf(f, i=0):
    return "1000_" + (str(f["attrs"].get("UFID") or "").strip() or f"{f['code']}_{f['sheet']}_{i}")


def _P(geom, **props):
    return {"geom": geom, "props": props}


def _lines(g):
    if g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g]
    if g.geom_type in ("MultiLineString", "GeometryCollection"):
        return [x for x in g.geoms if x.geom_type == "LineString"]
    return []


# ---------------------------------------------------------------------------
# 차도
# ---------------------------------------------------------------------------
def public_roads(feats, zone) -> list:
    out = []
    for i, f in enumerate(feats):
        if f["code"] != "A0020000" or f["gtype"] != "L":
            continue
        ln = shape_of(f)
        if not ln.intersects(zone):
            continue
        w = attr_float(f, "도로폭", 0.0) or 5.0
        surf = PAVE.get(f["attrs"].get("포장재질", "").strip(), "asphalt")
        for g in _lines(ln.intersection(zone)):
            if w < 3.0:  # 폭 3 m 미만 도로중심선은 보행로로 본다
                out.append(_P(g, kind="path", highway="footway", width=w, surface=surf, src=f["src"], osm=_uf(f, i), walk=True))
            else:
                out.append(_P(g, kind="road_public", highway="residential", width=w, surface=surf, src=f["src"], osm=_uf(f, i)))
    return out


def _measure_width(ln, edges, default=5.0):
    """차도 양옆 도로경계·인도 선까지의 거리로 폭을 잰다(5곳 중간값). 못 재면 default."""
    ws = []
    for t in (0.1, 0.3, 0.5, 0.7, 0.9):
        a = ln.interpolate(max(0, t * ln.length - 0.5))
        b = ln.interpolate(min(ln.length, t * ln.length + 0.5))
        m = ln.interpolate(t * ln.length)
        dx, dy = b.x - a.x, b.y - a.y
        k = math.hypot(dx, dy) or 1
        nx, ny = -dy / k, dx / k
        side = []
        for sgn in (1, -1):
            ray = LineString([(m.x + sgn * nx * 0.5, m.y + sgn * ny * 0.5), (m.x + sgn * nx * 10, m.y + sgn * ny * 10)])
            hit = ray.intersection(edges)
            if hit.is_empty:
                break
            side.append(m.distance(hit))
        if len(side) == 2:
            ws.append(sum(side))
    if len(ws) >= 2:
        return float(np.clip(np.median(ws), 3.0, 15.0)), True
    return default, False


def campus_roads(osm_net: dict, geo, zone, public=None, feats=None) -> list:
    pub = unary_union([p["geom"] for p in (public or []) if p["props"]["kind"] == "road_public"]) if public else None
    edges = None
    if feats is not None:
        eg = []
        for f in feats:
            if f["code"] in ("A0010000", "A0033320") and f["gtype"] in "LA":
                g = shape_of(f)
                if g.intersects(zone):
                    eg.append(g if f["gtype"] == "L" else g.boundary)
        edges = unary_union(eg)
    out = []
    for f in osm_net["features"]:
        p = f["properties"]
        if p.get("highway") not in ROADS or f["geometry"]["type"] != "LineString":
            continue
        ln = LineString([geo.to5186(*c) for c in f["geometry"]["coordinates"]])
        if not ln.intersects(zone):
            continue
        if pub is not None and not pub.is_empty and ln.intersection(pub.buffer(8)).length >= 0.7 * ln.length:
            continue  # 1:1,000 공공도로가 이미 있음
        for g in _lines(ln.intersection(zone)):
            if g.length < 1.0:
                continue
            if p.get("width"):
                try:
                    w, src_w = float(str(p["width"]).split()[0]), "OSM"
                except ValueError:
                    w, src_w = 5.0, "가상(폭)"
            elif edges is not None:
                w, ok = _measure_width(g, edges)
                src_w = "1:1000(2011)·1:1000(2013) 도로경계 사이" if ok else "가상(폭)"
            else:
                w, src_w = 5.0, "가상(폭)"
            surf = p.get("surface") if p.get("surface") in ("asphalt", "concrete") else "asphalt"
            out.append(_P(g, kind="road_campus", highway=p["highway"], width=round(w, 2), width_src=src_w, surface=surf,
                          surface_src="OSM" if p.get("surface") in ("asphalt", "concrete") else "가상(재질, 항공사진상 포장)",
                          src="OSM", osm=p.get("osm", "")))
    return out


# ---------------------------------------------------------------------------
# 보도: 인도 선(턱 선)을 차도 반대쪽으로 폭/2 옮김
# ---------------------------------------------------------------------------
def sidewalks(feats, zone, roads) -> list:
    rl = unary_union([r["geom"] for r in roads if r["props"]["kind"] in ("road_public", "road_campus")]) if roads else None
    bounds = unary_union([shape_of(f) for f in feats if f["code"] == "A0010000"]) if any(f["code"] == "A0010000" for f in feats) else None
    out = []
    for i, f in enumerate(feats):
        if f["code"] != "A0033320" or f["gtype"] != "L":
            continue
        ln = shape_of(f)
        if ln.geom_type != "LineString" or not ln.intersects(zone) or ln.length < 1.0:
            continue
        w = attr_float(f, "폭", 0.0) or 2.0
        # 차도가 왼쪽에 있는지 표본 점으로 다수결
        votes = 0
        for d in np.linspace(0.05, 0.95, max(3, int(ln.length / 10))):
            a = ln.interpolate(max(0, d * ln.length - 0.5))
            b = ln.interpolate(min(ln.length, d * ln.length + 0.5))
            m = ln.interpolate(d * ln.length)
            dx, dy = b.x - a.x, b.y - a.y
            k = math.hypot(dx, dy) or 1
            L = Point(m.x - dy / k, m.y + dx / k)
            R = Point(m.x + dy / k, m.y - dx / k)
            if rl is not None and not rl.is_empty and m.distance(rl) < 25:
                votes += 1 if L.distance(rl) < R.distance(rl) else -1
            elif bounds is not None:
                # 도로경계(대지 쪽 선)가 가까운 쪽이 보도 쪽 → 차도는 반대
                votes += -1 if L.distance(bounds) < R.distance(bounds) else 1
        if votes == 0:
            continue
        off = -w / 2 if votes > 0 else w / 2  # offset_curve: + 는 왼쪽
        g = ln.offset_curve(off)
        for gg in _lines(g.intersection(zone)):
            if gg.length < 1.0:
                continue
            out.append({"geom": gg, "curb": ln, "props": {"kind": "sidewalk", "highway": "footway", "width": w,
                        "surface": SW_MAT.get(f["attrs"].get("재질", "").strip(), "other"), "src": f["src"], "osm": _uf(f, i)}})
    return out


def mark_walkable(roads, sidewalks) -> None:
    sw = unary_union([s["geom"] for s in sidewalks]) if sidewalks else None
    for r in roads:
        if r["props"]["kind"] == "path":
            r["props"]["walk"] = True
            continue
        if sw is None or sw.is_empty:
            r["props"]["walk"] = True
            continue
        lim = r["props"]["width"] / 2 + 6.0
        g = r["geom"]
        ts = np.linspace(0, g.length, max(3, int(g.length / 5) + 1))
        near = sum(g.interpolate(t).distance(sw) <= lim for t in ts)
        r["props"]["walk"] = not (near / len(ts) > 0.5)


# ---------------------------------------------------------------------------
# 계단: 면 → 가운데 선. 벽 3 m 안이면 벽에 수직, 아니면 긴 방향
# ---------------------------------------------------------------------------
def _rect_axes(poly):
    r = poly.minimum_rotated_rectangle
    c = list(r.exterior.coords)[:4]
    e = [(c[i], c[(i + 1) % 4]) for i in range(4)]
    mid = lambda a, b: ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)  # noqa: E731
    l0, l1 = math.dist(*e[0]), math.dist(*e[1])
    # 축 A: e0·e2의 가운데를 잇는 선(길이 l1), 축 B: e1·e3의 가운데를 잇는 선(길이 l0)
    A = (LineString([mid(*e[0]), mid(*e[2])]), l0)
    B = (LineString([mid(*e[1]), mid(*e[3])]), l1)
    return A, B  # (선, 그 선에 수직인 폭)


def stairs(feats, zone, buildings=None, grad=None) -> list:
    """grad(x, y) -> (gx, gy): 땅 기울기(m/m). 벽 3 m 안이 아닌 계단은 기울기가 1% 넘으면 기울기 방향에 가까운 축."""
    blds = buildings if buildings is not None else [shape_of(f) for f in feats if f["code"] == "B0010000" and f["gtype"] == "A"]
    bu = unary_union(blds) if blds else None
    out = []
    for i, f in enumerate(feats):
        if f["code"] != "C0390000" or f["gtype"] != "A":
            continue
        if f["attrs"].get("구조", "").strip() == "스탠드":
            continue
        poly = shape_of(f)
        if poly.geom_type not in ("Polygon", "MultiPolygon") or not poly.intersects(zone) or poly.area < 0.3:
            continue
        (a_ln, a_w), (b_ln, b_w) = _rect_axes(poly)
        axis, width = (a_ln, a_w) if a_ln.length >= b_ln.length else (b_ln, b_w)
        if bu is not None and not bu.is_empty and poly.distance(bu) <= 3.0:
            # 벽에 가까운 쪽 끝이 벽에서 멀어지는 축 = 벽에 수직인 축
            def toward(ln):
                p, q = Point(ln.coords[0]), Point(ln.coords[-1])
                return abs(p.distance(bu) - q.distance(bu))
            axis, width = (a_ln, a_w) if toward(a_ln) >= toward(b_ln) else (b_ln, b_w)
        elif grad is not None:
            c = poly.centroid
            gx, gy = grad(c.x, c.y)
            if math.hypot(gx, gy) > 0.01:
                def along(ln):
                    (x0, y0), (x1, y1) = ln.coords[0], ln.coords[-1]
                    L = math.hypot(x1 - x0, y1 - y0) or 1.0
                    return abs((x1 - x0) * gx + (y1 - y0) * gy) / L
                axis, width = (a_ln, a_w) if along(a_ln) >= along(b_ln) else (b_ln, b_w)
        mat = "block" if "블럭" in f["attrs"].get("명칭", "") or "블록" in f["attrs"].get("명칭", "") else "concrete"
        out.append(_P(axis, kind="steps", highway="steps", width=round(width, 2), surface=mat, src=f["src"], osm=_uf(f, i),
                      surface_src=f["src"] if mat == "block" else "가상(재질)"))
    return out


# ---------------------------------------------------------------------------
# 건너는 곳·차량 진출입부·걷는 차도 잇기 + 턱 점
# ---------------------------------------------------------------------------
def _stripe_ratio(line, img, geo_full):
    if img is None:
        return 0.0
    n = max(2, int(line.length / 0.25))
    hit = 0
    for d in np.linspace(0, line.length, n):
        p = line.interpolate(d)
        x, y = geo_full.px_from5186(p.x, p.y)
        xi, yi = int(x), int(y)
        if 0 <= yi < img.shape[0] and 0 <= xi < img.shape[1]:
            hit += img[yi, xi].mean() > 200
    return hit / n


def crossings(sidewalks, roads, feats, aerial_full=None, geo_full=None) -> tuple:
    """보도 끝마다: (1) 차도를 건너지 않고 12 m 안의 다른 보도 끝 → 차량 진출입부(driveway),
    (2) 차도 중심선을 하나 건너는 30 m 안의 맞은편 보도 → 횡단보도(crosswalk)나 건너는 곳(plain),
    (3) 15 m 안의 걷는 차도 → 잇기(plain)."""
    cw = unary_union([shape_of(f) for f in feats if f["code"] == "A0043325" and f["gtype"] == "A"])
    road_all = [r for r in roads if r["props"]["kind"] in ("road_public", "road_campus")]
    road_u = unary_union([r["geom"] for r in road_all]) if road_all else LineString()
    walk_roads = [r for r in roads if r["props"].get("walk")]
    walk_u = unary_union([r["geom"] for r in walk_roads]) if walk_roads else LineString()
    parts, kerbs = [], []
    ends = []
    for k, s in enumerate(sidewalks):
        g = s["geom"]
        if g.is_ring or Point(g.coords[0]).distance(Point(g.coords[-1])) < 0.5:
            continue
        ends += [(k, Point(g.coords[0])), (k, Point(g.coords[-1]))]
    done = set()

    def kerb(pt, kind, src):
        kerbs.append({"xy": (pt.x, pt.y), "kind": kind, "src": src})

    # 진출입부로 보도가 이어지는 끝(12 m 안의 다른 보도 끝, 차도를 건너지 않음): 그 끝에서는 횡단보도만 건넌다
    cont = set()
    for i, (k, e) in enumerate(ends):
        for k2, e2 in ends:
            if k2 != k and e.distance(e2) <= 12.0 and (road_u.is_empty or not LineString([e, e2]).crosses(road_u)):
                cont.add(i)
                break

    cands = []
    for i_end, (k, e) in enumerate(ends):
        src_k = sidewalks[k]["props"]["src"]
        # (1) 진출입부
        best = None
        for k2, e2 in ends:
            if k2 == k:
                continue
            d = e.distance(e2)
            if d <= 12.0 and (best is None or d < best[0]):
                con = LineString([e, e2])
                if road_u.is_empty or not con.crosses(road_u):
                    best = (d, k2, e2)
        if best and frozenset([(k, e.wkt), (best[1], best[2].wkt)]) not in done:
            done.add(frozenset([(k, e.wkt), (best[1], best[2].wkt)]))
            con = LineString([e, best[2]])
            if con.length >= 0.3:
                parts.append(_P(con, kind="driveway", highway="footway", width=sidewalks[k]["props"]["width"],
                                surface="asphalt", surface_src="가상(재질)", src=src_k + " 인도 끊김", osm=f"link_dw_{len(parts)}"))
                kerb(e, "driveway", src_k + " 인도 끊김")
                kerb(best[2], "driveway", sidewalks[best[1]]["props"]["src"] + " 인도 끊김")
        # (2) 건너는 곳
        best = None
        for k2, s2 in enumerate(sidewalks):
            if k2 == k:
                continue
            q = nearest_points(e, s2["geom"])[1]
            d = e.distance(q)
            if d > 30.0 or d < 1.0:
                continue
            con = LineString([e, q])
            hits = [r for r in road_all if con.crosses(r["geom"])]
            if len(hits) != 1:
                continue
            # 차도와 거의 수직(45° 넘게)
            rg = hits[0]["geom"]
            t = rg.project(con.intersection(rg) if con.intersection(rg).geom_type == "Point" else e)
            a, b = rg.interpolate(max(0, t - 1)), rg.interpolate(min(rg.length, t + 1))
            v1 = np.array([b.x - a.x, b.y - a.y]); v2 = np.array([q.x - e.x, q.y - e.y])
            cosang = abs(v1 @ v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9)
            if cosang > math.cos(math.radians(45)):
                continue
            if d > hits[0]["props"]["width"] + 8.0:
                continue
            if best is None or d < best[0]:
                best = (d, k2, q, con)
        if best:
            d, k2, q, con = best
            key = frozenset([round(e.x, 1), round(e.y, 1), round(q.x, 1), round(q.y, 1)])
            if key not in done:
                done.add(key)
                if not cw.is_empty and con.intersects(cw):
                    kind, src = "crosswalk", "1:1000 횡단보도"
                elif _stripe_ratio(con, aerial_full, geo_full) >= 0.30:
                    kind, src = "crosswalk", "항공사진(횡단보도 줄무늬)"
                else:
                    kind, src = "plain", src_k + " 인도 끝"
                cands.append((0 if kind == "crosswalk" else (1 if i_end not in cont else 2), kind, src, con, e, q))
        # (3) 걷는 차도
        if not walk_u.is_empty:
            q = nearest_points(e, walk_u)[1]
            if 0.3 <= e.distance(q) <= 15.0:
                con = LineString([e, q])
                if not con.crosses(road_u.difference(walk_u.buffer(0.5))):
                    parts.append(_P(con, kind="link", highway="footway", width=sidewalks[k]["props"]["width"],
                                    surface="asphalt", surface_src="가상(재질)", src=src_k + " 인도 끝", osm=f"link_rd_{len(parts)}"))
                    kerb(e, "plain", src_k + " 인도 끝")
    # 횡단보도는 모두, 끝나는 보도의 건너는 곳은 10 m, 이어지는 보도의 건너는 곳은 25 m 간격으로만
    mids = []
    for rank, kind, src, con, e, q in sorted(cands, key=lambda c: (c[0], c[3].length)):
        m = con.interpolate(0.5, normalized=True)
        gap = {0: 0.0, 1: 10.0, 2: 25.0}[rank]
        if gap and any(m.distance(x) < gap for x in mids):
            continue
        mids.append(m)
        parts.append(_P(con, kind="crossing", highway="footway", footway="crossing" if kind == "crosswalk" else "",
                        width=3.0, width_src="가상(건너는 곳 폭)", surface="asphalt", surface_src="가상(재질)", src=src, osm=f"link_cx_{len(parts)}"))
        kerb(e, kind, src)
        kerb(q, kind, src)
    return parts, kerbs


# ---------------------------------------------------------------------------
# 건물 출입: 계단 출입(지도) + 이름 있는 건물마다 계단 없는 출입구(가상)
# ---------------------------------------------------------------------------
def building_name(f):
    n = f["attrs"].get("주기", "").strip()
    if n:
        return n
    n = f["attrs"].get("명칭", "").strip()
    return "" if n in GENERIC_NAMES else n


def entrances(feats, zone, stairs, paths, new_blds, steps=True, stepfree=True) -> tuple:
    """steps: 지도 계단 출입, stepfree: 이름 있는 건물마다 계단 없는 출입구(가상). paths는 계단 없이 갈 수 있는 길이어야 한다."""
    blds = []
    for f in feats:
        if f["code"] == "B0010000" and f["gtype"] == "A":
            g = shape_of(f)
            if g.geom_type in ("Polygon", "MultiPolygon") and g.centroid.within(zone):
                blds.append((g, building_name(f), f["src"]))
    parts, pts = [], []
    for st in (stairs if steps else []):
        a, b = Point(st["geom"].coords[0]), Point(st["geom"].coords[-1])
        best = None
        for bi, (g, name, src) in enumerate(blds):
            for end in (a, b):
                d = end.distance(g.exterior if g.geom_type == "Polygon" else g.boundary)
                if d <= 3.0 and (best is None or d < best[0]):
                    best = (d, bi, end)
        if best is None:
            continue
        d, bi, end = best
        g, name, _ = blds[bi]
        wall = nearest_points(end, g.exterior if g.geom_type == "Polygon" else g.boundary)[1]
        if end.distance(wall) >= 0.3:
            parts.append(_P(LineString([end, wall]), kind="entrance", highway="footway", width=st["props"]["width"],
                            surface="concrete", surface_src="가상(재질)", src=st["props"]["src"], osm=f"link_en_{len(parts)}", wall_end=True))
        pts.append({"xy": (wall.x, wall.y), "building": bi, "name": name, "kind": "steps", "src": st["props"]["src"]})
    if not stepfree or not paths:
        return parts, pts
    stair_zone = unary_union([s["geom"].buffer(2.0) for s in stairs]) if stairs else None
    walk = unary_union([p["geom"] for p in paths])
    if stair_zone is not None and not stair_zone.is_empty:
        walk = walk.difference(stair_zone)
    for bi, (g, name, src) in enumerate(blds):
        if not name or walk.is_empty or name.endswith("정문"):  # 정문은 건물이 아니라 길 위 출입 지점(팀 결정 2026-11-15)
            continue
        ring = g.exterior if g.geom_type == "Polygon" else g.boundary
        p_walk, p_wall = nearest_points(walk, ring)
        d = p_walk.distance(p_wall)
        if d > 60.0:
            continue
        if d < 1.2:  # 길이 벽에 붙어 있어도 출입 선을 1.2 m는 둔다(잇기 거리 1 m보다 길게): 길에 갈림 마디가 생겨야 계단 없는 구간으로 나뉜다
            c = g.centroid
            vx, vy = (p_wall.x - p_walk.x, p_wall.y - p_walk.y) if d > 1e-6 else (c.x - p_walk.x, c.y - p_walk.y)
            k = math.hypot(vx, vy) or 1.0
            p_wall = Point(p_walk.x + vx / k * 1.2, p_walk.y + vy / k * 1.2)
        if True:
            parts.append(_P(LineString([p_walk, p_wall]), kind="entrance", highway="footway", width=1.5, width_src="가상(폭)", surface="concrete", surface_src="가상(재질)",
                            src="가상(계단 없는 출입구)", osm=f"link_en_{len(parts)}", wall_end=True))
        pts.append({"xy": (p_wall.x, p_wall.y), "building": bi, "name": name, "kind": "stepfree", "src": "가상(계단 없는 출입구)"})
    return parts, pts
