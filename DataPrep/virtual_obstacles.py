"""2·3차 항목(가상): 측정 앱의 장애물 16종과 시설 7종을 길 위·옆에 놓는다.

칸 이름과 값의 뜻은 측정 앱(docs/js/fields.js)을 따른다. 실제 근거가 있는 것만 출처를 그렇게 적는다.
- 이지제주(2025-09): 주출입구 약 10 cm 단 + 5° 경사로, 휠체어·유모차 대여 있음
- OSM wheelchair=no 점: 높이·폭은 가상
- 시설 목록(공식 안내도 + 지도 이름): 화장실·출입구 자리
나머지는 모두 '가상'이다. 길 옆 낙차는 그쪽 땅을 실제로 낮춘다.
"""
import json
import math
import random

import numpy as np

import virtual_world as vw

PLACE = [("매표소", "ticket"), ("안내소", "info"), ("정문", "ticket"), ("식당", "food"), ("첫마을", "food"), ("카페", "food"),
         ("편의점", "shop"), ("한복", "shop"), ("체험가옥", "house")]


def _px_to_m(meta, px, py):
    return (px - meta["size_px"][0] / 2) * meta["m_per_px"], (meta["size_px"][1] / 2 - py) * meta["m_per_px"]


def _ll_to_m(meta, lon, lat):  # 경위도 -> Unity 좌표(동 m, 북 m)
    n = 256 * 2 ** meta["zoom"]
    sn = math.sin(math.radians(lat))
    px = (lon + 180) / 360 * n - meta["tile_origin_px"][0]
    py = (0.5 - math.log((1 + sn) / (1 - sn)) / (4 * math.pi)) * n - meta["tile_origin_px"][1]
    return _px_to_m(meta, px, py)


def _free_s(rng, seg, taken, lo=1.0, margin=1.5, tries=40):
    """구간 안에서 계단·턱·이미 놓은 것과 margin 넘게 떨어진 s."""
    L = seg["len"]
    if L < 2 * lo + 0.5:
        return None
    for _ in range(tries):
        s = round(rng.uniform(lo, L - lo), 2)
        if all(abs(s - t) > margin for t in taken) and not vw.in_steps(seg, s) and not vw._in_span(seg["steps"], s, 1.0):
            return s
    return None


def build_obstacles(inp, ter, world_segs, seed) -> dict:
    rng = random.Random(seed + 2)
    meta = json.loads((inp.site_dir / "aerial_z19.json").read_text(encoding="utf-8"))
    mseg = {s["id"]: s for s in inp.segs}
    W = [s for s in world_segs if not vw.is_loop(s)]  # 고리 구간은 표시값이 뒤집혀 빼고 놓는다
    taken = {s["id"]: [b["s"] for b in s["bumps"]] for s in world_segs}
    deg = {}
    for p in inp.pack["segs"]:
        deg[p["a"]] = deg.get(p["a"], 0) + 1
        deg[p["b"]] = deg.get(p["b"], 0) + 1
    road_nodes = {n for s in inp.segs if s["road"] for n in (s["a"], s["b"])}
    obs, fac = [], []

    def put(o, seg):
        o.setdefault("src", "가상")
        o["seg"] = seg["id"]
        obs.append(o)
        taken[seg["id"]].append(o["s"])

    def pick(cands, n):
        c = cands[:]
        rng.shuffle(c)
        return c[:n]

    walk = [s for s in W if not mseg[s["id"]]["road"]]
    # 좁은 곳 10, 틈 12
    for s in pick([s for s in walk if s["len"] >= 8 and s["w"] >= 1.8], 10):
        x = _free_s(rng, s, taken[s["id"]], 2.0)
        if x is None:
            continue
        v = rng.choice([72, 85, 95, 100, 104, 110, 120, 135])
        o2 = rng.random() < 0.5
        o = {"type": "narrow", "s": x, "value": v, "over2m": "yes" if o2 else "no"}
        if v <= 105:
            o["value2"] = v + rng.choice([0, 1, 2])
        if o2:
            o["over5m"] = rng.choice(["yes", "no"])
        o["s_end"] = round(min(s["len"] - 0.5, x + (rng.uniform(2.2, 6) if o2 else rng.uniform(0.6, 1.8))), 2)
        put(o, s)
    for s in pick(walk, 12):
        x = _free_s(rng, s, taken[s["id"]])
        if x is not None:
            put({"type": "gap", "s": x, "value": rng.choice([8, 12, 15, 20, 25, 35]), "dir": rng.choice(["cross", "cross", "parallel"]),
                 "remain_cm": rng.choice([0, 40, 60, 90]), "repeat": "no"}, s)
    # 못 감 2(그린 길), 끊긴 길 1, 표에 없는 것 2
    drawn = [s for s in W if mseg[s["id"]]["drawn"] and s["len"] >= 10]
    for s in pick(drawn, 3)[:2]:
        x = _free_s(rng, s, taken[s["id"]], 2.0, 3.0)
        if x is not None:
            put({"type": "nogo", "s": x, "s_end": round(min(s["len"] - 0.5, x + rng.uniform(3, 7)), 2), "side_line": rng.choice(["yes", "no"]),
                 "reason": rng.choice(["stones", "sink", "bumps"])}, s)
    for s in pick(drawn, 1):
        x = _free_s(rng, s, taken[s["id"]], 3.0)
        if x is not None:
            put({"type": "broken", "s": x}, s)
    for memo, s in zip(["가상: 나무뿌리가 솟음", "가상: 배수로 뚜껑이 들뜸"], pick(walk, 2)):
        x = _free_s(rng, s, taken[s["id"]])
        if x is not None:
            put({"type": "other", "s": x, "memo": memo}, s)
    # 위험: 길 옆 낙차 6, 차량과 함께 쓰는 길(차도 전부)
    for s in pick([s for s in walk if s["len"] >= 12 and not s["steps"]], 6):
        x = _free_s(rng, s, taken[s["id"]], 2.0, 3.0)
        if x is None:
            continue
        side = rng.choice(["left", "right"])
        low = rng.choice([side, "flat"])
        o = {"type": "hazard", "hazard": "drop", "s": x, "s_end": round(min(s["len"] - 1.0, x + rng.uniform(4, 10)), 2), "drop_side": side,
             "low_side": low, "guard": rng.choice(["rail", "kerb", "none"]), "depth_m": round(rng.uniform(0.8, 1.5), 2)}
        if low != "flat":
            o["leans"] = rng.choice(["yes", "no"])
        put(o, s)
    for s in W:
        if mseg[s["id"]]["road"]:
            put({"type": "hazard", "hazard": "shared", "s": 0.0, "s_end": s["len"]}, s)
    # 일시 막힘 2, 물 고임 6(흙·자갈 위), 쉬는 평지 8, 비켜설 곳 6, 회전 공간 5, 차량 진출입부 6
    for what, s in zip(["works", "parked"], pick(walk, 2)):
        x = _free_s(rng, s, taken[s["id"]])
        if x is not None:
            put({"type": "temp_block", "s": x, "what": what}, s)
    soft = [s for s in walk if any(x["material"] in ("soil", "gravel", "grass", "songi") for x in s["surf"])]
    for s in pick(soft, 6):
        x = _free_s(rng, s, taken[s["id"]])
        if x is not None:
            put({"type": "puddle", "s": x}, s)
    steep = [s for s in walk if s["len"] >= 8 and max(abs(vw.long_at(s, m)) for m in np.arange(1, s["len"] - 1, 2.0)) >= 4.5]
    for s in pick(steep, 8):
        x = _free_s(rng, s, taken[s["id"]])
        if x is not None:
            put({"type": "rest", "s": x, "flat": rng.choice(["yes", "no"])}, s)
    narrow_segs = [s for s in walk if s["w"] <= 1.8 and s["len"] >= 15]
    for s in pick(narrow_segs, 6):
        x = _free_s(rng, s, taken[s["id"]])
        if x is not None:
            put({"type": "passing", "s": x}, s)
    leaf = [s for s in walk if (deg.get(s["a"], 0) == 1 or deg.get(s["b"], 0) == 1) and s["len"] >= 3]
    for s in pick(leaf, 5):
        end_b = deg.get(s["b"], 0) == 1
        put({"type": "turn", "s": round(s["len"] - 1.0 if end_b else 1.0, 2), "w_cm": rng.randint(110, 200), "d_cm": rng.randint(110, 200)}, s)
    for s in leaf:
        end_b = deg.get(s["b"], 0) == 1
        put({"type": "dead_end", "s": round(s["len"] - 0.5 if end_b else 0.5, 2)}, s)
    at_road = [s for s in walk if (s["a"] in road_nodes or s["b"] in road_nodes) and s["len"] >= 4]
    for s in pick(at_road, 6):
        put({"type": "driveway", "s": round(1.2 if s["a"] in road_nodes else s["len"] - 1.2, 2), "cross": round(rng.uniform(1.0, 6.0), 1),
             "bump_mm": rng.choice([0, 10, 20, 35])}, s)

    # 시설 ------------------------------------------------------------------------
    pois = json.loads((inp.site_dir / "시설목록.geojson").read_text(encoding="utf-8"))["features"]

    wsd = {s["id"]: s for s in world_segs}

    def in_stairs(seg_id, s):  # 계단 0.3 m 안
        return any(st["s0"] - 0.3 < s < st["s1"] + 0.3 for st in wsd[seg_id]["steps"])

    def add_fac(f, seg_id, x, z):
        seg = mseg[seg_id]
        s, d = vw.project(seg, (x, z))
        if in_stairs(seg_id, s):
            # 계단 안에 놓이면, 0.5 m 안으로 비슷하게 가까운 계단 아닌 구간(같은 마디에 붙은 구간 등)으로 옮긴다
            alt = [(vw.project(mseg[w["id"]], (x, z)), w["id"]) for w in W if w["id"] != seg_id]
            alt = [(sd, wid) for sd, wid in alt if sd[1] <= d + 0.5 and not in_stairs(wid, sd[0])]
            if alt:
                (s, d), seg_id = min(alt, key=lambda t: t[0][1])
                seg = mseg[seg_id]
            else:  # 없으면 가까운 계단 끝 밖으로
                st = next(st for st in wsd[seg_id]["steps"] if st["s0"] - 0.3 < s < st["s1"] + 0.3)
                s = st["s0"] - 0.35 if s - st["s0"] < st["s1"] - s else st["s1"] + 0.35
        f.update(seg=seg_id, s=round(min(max(s, 0.3), seg["len"] - 0.3), 2), x=round(x, 2), z=round(z, 2))
        f.setdefault("dest", "door")
        fac.append(f)

    wseg_ids = {s["id"] for s in W}
    # OSM 화장실의 장애인 칸 표시(toilets:wheelchair): 자리 10 m 안이면 무작위 대신 이 값을 쓴다
    osm_wc = []
    for f in inp.osm["features"]:
        t = f["properties"]
        if t.get("amenity") == "toilets" and t.get("toilets:wheelchair") in ("yes", "no"):
            ring = f["geometry"]["coordinates"][0] if f["geometry"]["type"] == "Polygon" else [f["geometry"]["coordinates"]]
            ring = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
            lon, lat = sum(c[0] for c in ring) / len(ring), sum(c[1] for c in ring) / len(ring)
            osm_wc.append((_ll_to_m(meta, lon, lat), t["toilets:wheelchair"]))
    for p in pois:
        q = p["properties"]
        if q["seg"] not in wseg_ids:
            continue
        x, z = _px_to_m(meta, *q["aerial_px"])
        name = q["name"]
        if q["type"] == "화장실":
            stall = rng.random() < 0.7
            where = "자리는 OSM 화장실 건물" if q["how"].startswith("OSM") else "자리는 공식 안내도(추정 포함)"
            src = f"가상({where})"
            near = [v for (ox, oz), v in osm_wc if math.hypot(ox - x, oz - z) <= 10]
            if near:
                stall = near[0] == "yes"
                src = f"OSM toilets:wheelchair={near[0]}(장애인 칸 있음 여부만, 칸 크기 등은 가상), {where}"
            # 시설 목록에서 건물 안에 찍힌 화장실은 실제 건물이 있으므로 3D에서 가상 상자를 세우지 않는다
            on_bld = (q.get("building") or {}).get("dist_m") == 0
            f = {"type": "toilet", "name": name, "stall": "yes" if stall else "no", "src": src, "on_building": on_bld}
            if stall:
                f.update(lock=rng.choice(["open", "open", "ask"]), door_cm=rng.choice([82, 88, 95, 100]), w_cm=rng.randint(150, 210),
                         d_cm=rng.randint(170, 230), side_cm=rng.choice([60, 75, 85]), bump_mm=rng.choice([0, 0, 10, 25]))
            add_fac(f, q["seg"], x, z)
        elif name == "정문" or (q["type"] in ("시설", "체험가옥") and q.get("building")):
            place = next((v for k, v in PLACE if k in name), "hall")
            f = {"type": "entrance", "name": name, "place": place, "door_cm": rng.choice([78, 85, 90, 95, 110]),
                 "sill_mm": rng.choice([0, 0, 15, 20, 40, 60]), "door": rng.choice(["swing", "slide", "none"]),
                 "src": "가상(자리는 공식 안내도·OSM)"}
            if name == "정문":
                f.update(sill_mm=100, door="none", src="이지제주(2025-09): 주출입구 바닥이 지면보다 약 10 cm 높음(폭은 가상)")
                add_fac(f, q["seg"], x, z)
                add_fac({"type": "ramp", "name": "정문 양옆 경사로", "slope_low": 5.0, "slope_mid": 5.0, "slope_top": 5.0, "w_cm": 120,
                         "len_m": round(0.1 / math.tan(math.radians(5)), 1), "src": "이지제주(2025-09): 양옆 5° 경사로(폭·길이는 가상)"}, q["seg"], x, z)
                continue
            add_fac(f, q["seg"], x, z)
        elif name == "주차장":
            # 장애인 주차 칸 자리는 OSM parking_space=disabled(있으면), 칸 크기·기울기는 가상
            dis = [f for f in inp.osm["features"] if f["properties"].get("parking_space") == "disabled"]
            dis.sort(key=lambda f: f["geometry"]["type"] != "Polygon")
            src, px, pz, sid = "가상(장애인 전용 주차구역 있음은 이지제주)", x, z, q["seg"]
            if dis:
                g = dis[0]["geometry"]
                ring = g["coordinates"][0] if g["type"] == "Polygon" else [g["coordinates"]]
                ring = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
                px, pz = _ll_to_m(meta, sum(c[0] for c in ring) / len(ring), sum(c[1] for c in ring) / len(ring))
                sid = min(W, key=lambda s: vw.project(mseg[s["id"]], (px, pz))[1])["id"]
                cap = dis[0]["properties"].get("capacity")
                src = f"OSM parking_space=disabled(자리{', ' + cap + '칸' if cap else ''}), 있음은 이지제주, 칸 크기·기울기는 가상"
            add_fac({"type": "parking", "name": "장애인 주차", "w_cm": 330, "l_cm": 500, "slope": 0.8, "path": "가상: 정문까지 평지 약 40 m",
                     "src": src}, sid, px, pz)
        elif "안내소" in name:
            for what, ex, memo, src in (("rental_wc", "yes", "", "이지제주(2025-09): 휠체어 대여 있음"),
                                        ("rental_st", "yes", "", "이지제주(2025-09): 유모차 대여 있음"),
                                        ("hours", "yes", "가상: 09:00~18:00(홈페이지가 닫혀 확인 못 함)", "가상")):
                add_fac({"type": "service", "name": name, "what": what, "exists": ex, "memo": memo, "src": src}, q["seg"], x, z)
    # OSM wheelchair=no 출입구 점
    for f in inp.osm["features"]:
        p = f["properties"]
        if f["geometry"]["type"] != "Point" or p.get("wheelchair") != "no":
            continue
        lon, lat = f["geometry"]["coordinates"]
        x, z = _ll_to_m(meta, lon, lat)
        best = min(W, key=lambda s: vw.project(mseg[s["id"]], (x, z))[1])
        if vw.project(mseg[best["id"]], (x, z))[1] > 15:
            continue
        add_fac({"type": "entrance", "name": p.get("name", "출입구"), "place": "house", "door_cm": rng.choice([70, 75, 80]),
                 "sill_mm": rng.choice([120, 150, 180, 220]), "door": "swing", "src": "OSM wheelchair=no(높이·폭은 가상)"}, best["id"], x, z)
    # 가상 경사로 4(가파른 구간), 연석경사로 8(보행로가 차도와 만나는 끝), 쉴 곳 10
    for s in pick(steep, 4):
        x = _free_s(rng, s, [], 1.5, 0)
        if x is None:
            continue
        a, b = max(0.5, x - 2), min(s["len"] - 0.5, x + 2)
        p, _ = vw.point_at(mseg[s["id"]], x)
        add_fac({"type": "ramp", "name": "가상 경사로", "slope_low": round(vw.long_at(s, a + 0.5), 1), "slope_mid": round(vw.long_at(s, x), 1),
                 "slope_top": round(vw.long_at(s, b - 0.5), 1), "w_cm": int(round(s["w"] * 100)), "len_m": round(b - a, 1), "dest": "main",
                 "s0": a, "s1": b, "src": "가상"}, s["id"], *p)
    for s in pick(at_road, 8):
        end = 0.3 if s["a"] in road_nodes else s["len"] - 0.3
        p, _ = vw.point_at(mseg[s["id"]], end)
        add_fac({"type": "curb_ramp", "name": "가상 연석경사로", "w_cm": rng.choice([90, 110, 150]), "slope": round(rng.uniform(3, 9), 1),
                 "end_mm": rng.choice([0, 5, 10, 20]), "dest": "main", "src": "가상"}, s["id"], *p)
    for s in pick(walk, 10):
        x = _free_s(rng, s, taken[s["id"]])
        if x is None:
            continue
        p, _ = vw.point_at(mseg[s["id"]], x)
        add_fac({"type": "bench", "name": "가상 벤치", "many": rng.choice(["no", "yes"]), "dest": "main", "src": "가상"}, s["id"], *p)

    _lower_drops(inp, ter, world_segs, obs)
    return {"obstacles": obs, "facilities": fac}


def _lower_drops(inp, ter, world_segs, obs):
    """길 옆 낙차: 그쪽 땅(길 가장자리 0.6 m 밖 ~ 6 m)을 길보다 depth만큼 낮춘다. 다른 길 아래는 건드리지 않는다."""
    import virtual_extras as vx
    tree, half, _ = vx._path_tree(inp)
    mseg = {s["id"]: s for s in inp.segs}
    wseg = {s["id"]: s for s in world_segs}
    flat = ter.h.ravel()
    n = ter.n
    for o in obs:
        if o["type"] != "hazard" or o["hazard"] != "drop":
            continue
        m, w = mseg[o["seg"]], wseg[o["seg"]]
        pr = vw.seg_profile(w)
        for x in np.arange(o["s"], o["s_end"] + 0.01, 0.5):
            p, d = vw.point_at(m, x)
            side = np.array([-d[1], d[0]]) * (1 if o["drop_side"] == "left" else -1)
            h = vw.height_at(pr, x) - o["depth_m"]
            for off in np.arange(m["w"] / 2 + 0.6, m["w"] / 2 + 6.01, 0.5):
                q = p + side * off
                if vx._clearance(tree, half, q)[0] < 0.5:
                    continue
                ix = int(round((q[0] - ter.origin) / ter.cell))
                iz = int(round((q[1] - ter.origin) / ter.cell))
                for jz in (iz - 1, iz, iz + 1):
                    for jx in (ix - 1, ix, ix + 1):
                        if 0 <= jx < n and 0 <= jz < n:
                            gq = np.array([ter.origin + jx * ter.cell, ter.origin + jz * ter.cell])
                            if vx._clearance(tree, half, gq)[0] >= 0.5:
                                flat[jz * n + jx] = min(flat[jz * n + jx], h)
    ter.h = flat.reshape(n, n)
