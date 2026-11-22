"""제주대 장애물·시설(설계 6장 마, 계획 Task 9). 칸은 민속촌 virtual_obstacles.py의 같은 type과 같다.

공개 지도 근거가 있는 것
- 길 옆 낙차: 1:1,000 옹벽·석축(높이)이 걷는 길 가장자리 1 m 안에 5 m 넘게 나란하고, 벽 너머 땅이 길보다 0.3 m 넘게 낮은 곳
- 막다른 길: 연결망(끝 마디가 하나)
- 차량 진출입부: 1:1,000 인도 선이 같은 쪽에서 끊긴 곳(맵 자료 kerbs의 driveway)
- 차량과 함께 쓰는 길: 걷는 차도 전부
- 출입구 자리: 1:1,000 계단 출입(지도) + 계단 없는 출입구(가상)
- 화장실·주차장 자리: OSM
나머지 종류와 크기·문턱 등은 가상(src '가상').
"""
import json
import math
import random

import numpy as np

import common
import virtual_world as vw

PLACE = "hall"


def _free_s(rng, seg, taken, lo=1.0, margin=1.5, tries=40):
    L = seg["len"]
    if L < 2 * lo + 0.5:
        return None
    for _ in range(tries):
        s = round(rng.uniform(lo, L - lo), 2)
        if all(abs(s - t) > margin for t in taken) and not vw.in_steps(seg, s) and not vw._in_span(seg["steps"], s, 1.0):
            return s
    return None


def _drops(inp, ter, W, mseg, walls):
    """옹벽·석축이 길 옆에 나란한 곳: [(seg, s0, s1, side, depth, wall_src)]."""
    out = []
    wl = [(np.array(w["p"], float).reshape(-1, 2), w["h"], w["src"]) for w in walls if w["h"] >= 0.5]
    for s in W:
        m = mseg[s["id"]]
        if m["road"] or s["len"] < 6:
            continue
        xs = np.arange(0.5, s["len"] - 0.5, 1.0)
        hit = []
        for x in xs:
            p, d = vw.point_at(m, x)
            left = np.array([-d[1], d[0]])
            best = None
            for q, h, src in wl:
                # 선분까지 거리
                a, b = q[:-1], q[1:]
                ab = b - a
                t = np.clip(((p - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-12), 0, 1)
                foot = a + ab * t[:, None]
                dist = np.hypot(*(foot - p).T)
                i = int(np.argmin(dist))
                if dist[i] <= m["w"] / 2 + 1.0 and (best is None or dist[i] < best[0]):
                    side = "left" if (foot[i] - p) @ left > 0 else "right"
                    best = (dist[i], h, src, side)
            if best is None:
                hit.append(None)
                continue
            _, h, src, side = best
            sg = 1 if side == "left" else -1
            beyond = p + left * sg * (m["w"] / 2 + 2.0)
            path_h = vw.height_at(vw.seg_profile(s), x)
            depth = path_h - ter.height(*beyond)
            hit.append((side, min(h, depth), src) if depth > 0.3 else None)
        # 같은 쪽으로 5 m 넘게 이어진 토막
        i = 0
        while i < len(xs):
            if hit[i] is None:
                i += 1
                continue
            j = i
            while j + 1 < len(xs) and hit[j + 1] is not None and hit[j + 1][0] == hit[i][0]:
                j += 1
            if xs[j] - xs[i] >= 5.0:
                depth = max(hit[k][1] for k in range(i, j + 1))
                out.append((s, float(xs[i]), float(xs[j]), hit[i][0], round(float(depth), 2), hit[i][2]))
            i = j + 1
    return out


def driveway_bump(bumps, s):
    """진출입부 턱 높이: 3.1 m 안 첫 턱의 높이를 옮겨 적는다. 그 턱이 '높이 모름'(거리뷰 반영, 2026-11-22)이면
    진출입부 턱도 못 잼으로 둔다 → (bump_mm, unread)."""
    near = [b for b in bumps if abs(b["s"] - s) <= 3.1]
    if not near:
        return 0, None
    if near[0].get("unread"):
        return None, ["bump_mm"]
    return near[0]["mm"], None


def build_obstacles(inp, ter, world_segs, seed, mp, ter_pre=None) -> dict:
    rng = random.Random(seed + 2)
    geo = common.load_geo()
    mseg = {s["id"]: s for s in inp.segs}
    W = [s for s in world_segs if not vw.is_loop(s)]
    wsd = {s["id"]: s for s in world_segs}
    taken = {s["id"]: [b["s"] for b in s["bumps"]] for s in world_segs}
    deg = {}
    for p in inp.pack["segs"]:
        deg[p["a"]] = deg.get(p["a"], 0) + 1
        deg[p["b"]] = deg.get(p["b"], 0) + 1
    obs, fac = [], []

    def put(o, seg):
        o.setdefault("src", "가상")
        o["seg"] = seg["id"]
        obs.append(o)
        taken[seg["id"]].append(o["s"])

    def pick(c, n):
        c = c[:]
        rng.shuffle(c)
        return c[:n]

    walk = [s for s in W if not mseg[s["id"]]["road"]]
    # 실제 근거 ----------------------------------------------------------------
    for s, a, b, side, depth, src in _drops(inp, ter_pre or ter, W, mseg, mp.get("walls", [])):
        if vw._in_span(s["steps"], a, 0.3) or vw._in_span(s["steps"], b, 0.3):
            continue
        put({"type": "hazard", "hazard": "drop", "s": round(a, 2), "s_end": round(b, 2), "drop_side": side, "low_side": side,
             "guard": rng.choice(["rail", "kerb", "none"]), "depth_m": depth, "leans": rng.choice(["yes", "no"]),
             "src": f"{src} 옹벽·석축(자리·높이), 난간·기울기는 가상"}, s)
    for s in W:
        if mseg[s["id"]].get("kind", "").startswith("road"):  # 구간의 주된 종류가 차도일 때만(pack road는 차도 조각이 하나만 있어도 참)
            src = "OSM 차도(보도 없음)" if mseg[s["id"]]["kind"] == "road_campus" else f"{mseg[s['id']]['surf_src'][0]['src']} 공공도로(보도 없음)"
            put({"type": "hazard", "hazard": "shared", "s": 0.0, "s_end": s["len"], "src": src}, s)
    leaf = [s for s in W if deg.get(s["a"], 0) == 1 or deg.get(s["b"], 0) == 1]
    for s in leaf:
        end_b = deg.get(s["b"], 0) == 1
        x = round(s["len"] - 0.5 if end_b else 0.5, 2)
        if not vw.in_steps(s, x):
            put({"type": "dead_end", "s": x, "src": "연결망(끝 마디가 하나)"}, s)
    for s in W:
        for k in mseg[s["id"]].get("kerbs", []):
            if k["kind"] != "driveway":
                continue
            bm, unread = driveway_bump(s["bumps"], k["s"])
            x = round(min(max(k["s"], 0.3), s["len"] - 0.3), 2)
            if vw.in_steps(s, x) or any(o["seg"] == s["id"] and o["type"] == "driveway" and abs(o["s"] - x) < 2 for o in obs):
                continue
            o = {"type": "driveway", "s": x, "cross": round(rng.uniform(1.0, 6.0), 1), "bump_mm": bm,
                 "src": f"{k['src']}(자리), 기울기는 가상"}
            if unread:
                o["unread"] = unread
            put(o, s)
    # 가상 -----------------------------------------------------------------------
    for s in pick([s for s in walk if s["len"] >= 8 and s["w"] >= 1.8], 6):
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
    for s in pick(walk, 8):
        x = _free_s(rng, s, taken[s["id"]])
        if x is not None:
            put({"type": "gap", "s": x, "value": rng.choice([8, 12, 15, 20, 25, 35]), "dir": rng.choice(["cross", "cross", "parallel"]),
                 "remain_cm": rng.choice([0, 40, 60, 90]), "repeat": "no"}, s)
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
    for what, s in zip(["works", "parked"], pick(walk, 2)):
        x = _free_s(rng, s, taken[s["id"]])
        if x is not None:
            put({"type": "temp_block", "s": x, "what": what}, s)
    soft = [s for s in walk if any(x["material"] in ("soil", "gravel", "grass", "songi") for x in s["surf"])]
    for s in pick(soft, 4):
        x = _free_s(rng, s, taken[s["id"]])
        if x is not None:
            put({"type": "puddle", "s": x}, s)
    steep = [s for s in walk if s["len"] >= 8 and max(abs(vw.long_at(s, m)) for m in np.arange(1, s["len"] - 1, 2.0)) >= 4.5]
    for s in pick(steep, 6):
        x = _free_s(rng, s, taken[s["id"]])
        if x is not None:
            put({"type": "rest", "s": x, "flat": rng.choice(["yes", "no"])}, s)
    for s in pick([s for s in walk if s["w"] <= 1.8 and s["len"] >= 15], 4):
        x = _free_s(rng, s, taken[s["id"]])
        if x is not None:
            put({"type": "passing", "s": x}, s)
    for s in pick([s for s in leaf if s["len"] >= 3 and not mseg[s["id"]]["road"]], 4):
        end_b = deg.get(s["b"], 0) == 1
        x = round(s["len"] - 1.0 if end_b else 1.0, 2)
        if not vw.in_steps(s, x):
            put({"type": "turn", "s": x, "w_cm": rng.randint(110, 200), "d_cm": rng.randint(110, 200)}, s)

    # 시설 ------------------------------------------------------------------------
    def in_stairs(sid, s):
        return any(st["s0"] - 0.3 < s < st["s1"] + 0.3 for st in wsd[sid]["steps"])

    def add_fac(f, x, z, sid=None):
        cand = W if sid is None else [wsd[sid]]
        best = None
        for w in cand:
            s, d = vw.project(mseg[w["id"]], (x, z))
            if in_stairs(w["id"], s):
                continue
            if best is None or d < best[0] - 0.5 or (abs(d - best[0]) <= 0.5 and best[2]):
                best = (d, w["id"], False, s)
        if best is None or best[0] > 20:
            return False
        d, sid, _, s = best
        L = wsd[sid]["len"]
        f.update(seg=sid, s=round(min(max(s, 0.3), L - 0.3), 2), x=round(x, 2), z=round(z, 2))
        f.setdefault("dest", "door")
        fac.append(f)
        return True

    ents = json.loads((common.SITE_DIR / "entrances.geojson").read_text(encoding="utf-8"))["features"]
    lib_done = False
    for e in ents:
        p = e["properties"]
        x, z = geo.unity(*geo.px(*e["geometry"]["coordinates"]))
        if p["kind"] == "steps":
            f = {"type": "entrance", "name": p.get("name") or "건물 출입구", "place": PLACE, "door_cm": rng.choice([85, 90, 95, 110, 120]),
                 "sill_mm": rng.choice([0, 0, 15, 20, 40]), "door": rng.choice(["swing", "slide", "none"]),
                 "src": f"{p['src']} 계단 출입(자리), 문 폭·문턱은 가상", "steps_before": True}
        else:
            f = {"type": "entrance", "name": p.get("name") or "건물 출입구", "place": PLACE, "door_cm": rng.choice([90, 95, 110, 120]),
                 "sill_mm": rng.choice([0, 0, 5, 10, 15, 20]), "door": rng.choice(["swing", "slide", "none"]), "src": "가상(계단 없는 출입구)"}
        if add_fac(f, x, z) and not lib_done and "도서관" in (p.get("name") or "") and p["kind"] == "stepfree":
            add_fac({"type": "service", "name": p["name"], "what": "hours", "exists": "yes", "memo": "가상: 09:00~22:00", "src": "가상"}, x, z)
            lib_done = True
    osm = json.loads((common.SITE_DIR / "osm_features.geojson").read_text(encoding="utf-8"))["features"]

    def center(g):
        ring = g["coordinates"][0] if g["type"] == "Polygon" else [g["coordinates"]]
        ring = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
        lon, lat = sum(c[0] for c in ring) / len(ring), sum(c[1] for c in ring) / len(ring)
        return geo.unity(*geo.px(lon, lat))
    for f in osm:
        t = f["properties"]
        if t.get("amenity") == "toilets":
            x, z = center(f["geometry"])
            wc = t.get("toilets:wheelchair")
            stall = (wc == "yes") if wc in ("yes", "no") else rng.random() < 0.7
            src = f"OSM toilets:wheelchair={wc}(장애인 칸 여부만), 자리는 OSM" if wc in ("yes", "no") else "가상(장애인 칸), 자리는 OSM 화장실"
            g = {"type": "toilet", "name": t.get("name", "화장실"), "stall": "yes" if stall else "no", "src": src, "on_building": True}
            if stall:
                g.update(lock=rng.choice(["open", "open", "ask"]), door_cm=rng.choice([82, 88, 95, 100]), w_cm=rng.randint(150, 210),
                         d_cm=rng.randint(170, 230), side_cm=rng.choice([60, 75, 85]), bump_mm=rng.choice([0, 0, 10, 25]))
            add_fac(g, x, z)
    lots = [f for f in osm if f["properties"].get("amenity") == "parking" and f["geometry"]["type"] == "Polygon"]
    for f in pick(lots, 2):
        x, z = center(f["geometry"])
        add_fac({"type": "parking", "name": "장애인 주차", "w_cm": 330, "l_cm": 500, "slope": round(rng.uniform(0.5, 2.5), 1),
                 "path": "가상", "src": "가상(장애인 주차 칸), 주차장 자리는 OSM"}, x, z)
    for s in pick(steep, 4):
        x = _free_s(rng, s, [], 1.5, 0)
        if x is None:
            continue
        a, b = max(0.5, x - 2), min(s["len"] - 0.5, x + 2)
        p, _ = vw.point_at(mseg[s["id"]], x)
        add_fac({"type": "ramp", "name": "가상 경사로", "slope_low": round(vw.long_at(s, a + 0.5), 1), "slope_mid": round(vw.long_at(s, x), 1),
                 "slope_top": round(vw.long_at(s, b - 0.5), 1), "w_cm": int(round(s["w"] * 100)), "len_m": round(b - a, 1), "dest": "main",
                 "s0": a, "s1": b, "src": "가상(경사는 공개 지도 땅 높이)"}, *p, sid=s["id"])
    cr = [(s, k) for s in W for k in mseg[s["id"]].get("kerbs", []) if k["kind"] == "crosswalk"]
    low = [(s, k) for s in W for k in mseg[s["id"]].get("kerbs", []) if k["kind"] == "plain"]
    for s, k in cr + pick(low, max(0, 8 - len(cr))):
        x = min(max(k["s"], 0.3), s["len"] - 0.3)
        if vw.in_steps(s, x):
            continue
        p, _ = vw.point_at(mseg[s["id"]], x)
        add_fac({"type": "curb_ramp", "name": "가상 연석경사로", "w_cm": rng.choice([90, 110, 150]), "slope": round(rng.uniform(3, 9), 1),
                 "end_mm": rng.choice([0, 5, 10, 20]), "dest": "main", "src": f"가상(연석경사로), 자리는 {k['src']}"}, *p, sid=s["id"])
    for s in pick(walk, 8):
        x = _free_s(rng, s, taken[s["id"]])
        if x is None:
            continue
        p, _ = vw.point_at(mseg[s["id"]], x)
        add_fac({"type": "bench", "name": "가상 벤치", "many": rng.choice(["no", "yes"]), "dest": "main", "src": "가상"}, *p, sid=s["id"])
    if not lib_done and fac:
        e = next(f for f in fac if f["type"] == "entrance")
        add_fac({"type": "service", "name": e["name"], "what": "hours", "exists": "yes", "memo": "가상: 09:00~18:00", "src": "가상"}, e["x"], e["z"], sid=e["seg"])
    return {"obstacles": obs, "facilities": fac}
