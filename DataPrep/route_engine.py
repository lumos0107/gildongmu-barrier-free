"""경로 추천 앱 첫 판: 경로 입력 파일(bf-route-input-1)로 이동 유형별 길을 찾는다(다익스트라 기본판).
설계: Docs/2026-11-15-경로앱-설계.md · 계획: Docs/2026-11-15-경로앱-작업계획.md
대상지와 상관없이 경로 입력 · 구간표(pack) · 시설 목록 파일만 받는다. 실측 뒤에는 경로 입력 파일만 바꾼다.
"""
import argparse
import heapq
import json
import math
import pathlib
import sys
from dataclasses import dataclass, field

if str(pathlib.Path(__file__).resolve().parent) not in sys.path:  # python -I로 직접 실행해도 같은 폴더의 route_cost를 찾게
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import route_cost as RC  # noqa: E402

MODES = ("manual", "power", "stroller")
EPS = 1e-9
# 판정 기준(설계 3장, 측정 매뉴얼 기준 환산표 · 규칙표 uncertain · bump.recheck_mm, 11/15 팀 결정)
SLOPE = {"manual": {"block": 4.8, "unc": (4.5, 5.0)}, "power": {"block": 5.8, "unc": (5.5, 5.9)}}  # 유아차는 막지 않음
BUMP_UNC = (18, 22)  # 이 안이면 불확실, 넘으면 막힘(세 유형)
WIDTH_BLOCK, WIDTH_UNC = 80, 90  # cm: 80 미만 막힘, 80 이상 90 미만 불확실
# 틈(11/15 팀 결정, 두 번째 판): 진행 방향과 나란한 틈만 본다. 13 mm 넘으면 막힘, 10~13 mm 불확실(세 유형),
# 틈을 피해 이어지는 남은 폭이 80 cm 이상이면 막지 않는다. 13 mm는 측정 매뉴얼이 인용한 미국 장애인법 기준.
GAP_UNC = (10, 13)
GAP_AVOID_CM = 80
CROSS_COST_FROM = 2.3  # 1/25
LONG_COST_FROM = 3.2   # 1/18
BLOCK_TYPES = {"steps": "계단", "nogo": "못 감 구간", "broken": "끊긴 길"}
CLOSED = {"no_entry": "출입 금지", "not_path": "길 아님"}  # 구간 확인 결과(저녁 도구 status · blocked)
RANK = {"ok": 0, "uncertain": 1, "blocked": 2}


@dataclass
class Judgement:
    state: str = "ok"
    reasons: list = field(default_factory=list)
    cost: float = 0.0
    notes: list = field(default_factory=list)
    no_cross: int = 0  # 좌우 값이 빈 지점 수(길 전체에서 더함)

    def worse(self, state, reason):
        if RANK[state] > RANK[self.state]:
            self.state = state
        if reason not in self.reasons:
            self.reasons.append(reason)


def _in(x, lo, hi):
    return lo - EPS <= x <= hi + EPS


def _slope_state(mag: float, mode: str):
    """앞뒤 기울기 크기 하나의 판정('uncertain' · 'blocked' · None). 유아차는 막지 않는다."""
    r = SLOPE.get(mode)
    if r and _in(mag, *r["unc"]):
        return "uncertain"
    if r and mag >= r["block"] - EPS:
        return "blocked"
    return None


def _bump_state(mm):
    if mm is None:
        return None
    if mm > BUMP_UNC[1] + EPS:
        return "blocked"
    if mm >= BUMP_UNC[0] - EPS:
        return "uncertain"
    return None


def _width_state(cm):
    if cm is None:
        return None
    if cm < WIDTH_BLOCK - EPS:
        return "blocked"
    if cm < WIDTH_UNC - EPS:
        return "uncertain"
    return None


def _facility_rules(j, items, mode, lo, hi):
    """가중치 경로(2026-11-21 팀 결정): 본선 경사로 · 연석경사로와 진출입부 턱을 판정에 넣고, 물 고임 · 회전 공간은 안내만."""
    for f in items.get("facilities") or []:
        if f.get("dest") != "main" or f.get("s") is None or not _in(f["s"], lo, hi):
            continue
        t = f.get("type")
        if t == "curb_ramp":
            name, slopes, end = "연석경사로", [f.get("slope")], f.get("end_mm")
        elif t == "ramp":
            name, slopes, end = "경사로", [f.get(k) for k in ("slope_low", "slope_mid", "slope_top")], None
        else:
            continue
        slopes = [abs(x) for x in slopes if x is not None]
        if slopes:
            mag = max(slopes)
            st = _slope_state(mag, mode)
            if st:
                j.worse(st, f"{name} {mag:.1f}°")
        elif t == "ramp" and "경사로 기울기 기록 없음" not in j.notes:
            j.notes.append("경사로 기울기 기록 없음")
        st = _bump_state(end)
        if st:
            j.worse(st, f"{name} 끝 턱 {end:g} mm")
        st = _width_state(f.get("w_cm"))
        if st:
            j.worse(st, f"{name} 폭 {f['w_cm']:g} cm")
    bars = items["barriers"]
    for x in bars:
        t, s = x.get("type"), x.get("s")
        if s is None or not _in(s, lo, hi):
            continue
        if t == "puddle" and "물 고임(안내만)" not in j.notes:
            j.notes.append("물 고임(안내만)")
        elif t == "turn" and "회전 공간 기록(안내만)" not in j.notes:
            j.notes.append("회전 공간 기록(안내만)")
        elif t == "driveway":
            mm = x.get("bump_mm")
            st = _bump_state(mm)
            if not st:
                continue
            near = [y for y in bars if y.get("type") == "bump" and y.get("s") is not None and abs(y["s"] - s) <= 1 + EPS
                    and _in(y["s"], lo, hi) and y.get("route_value") is not None and not y.get("unmeasured")]
            worst_near = max((_bump_state(y["route_value"]) or "ok" for y in near), key=RANK.get, default="ok")
            if RANK[st] <= RANK[worst_near]:
                continue  # 같은 자리 턱 기록이 같거나 더 나쁨: 이유를 하나만 둔다
            for y in near:  # 진출입부 턱이 더 나쁨: 같은 턱의 덜 나쁜 이유를 지우고 하나로
                r = f"턱 {y['route_value']:g} mm"
                if r in j.reasons:
                    j.reasons.remove(r)
            j.worse(st, f"진출입부 턱 {mm:g} mm")


def judge(items: dict, mode: str, lo: float = 0.0, hi: float = None, very_bad_blocks: bool = True,
          facility_rules: bool = False) -> Judgement:
    """한 구간(또는 lo~hi 부분)의 판정. items는 경로 입력의 그 구간 항목(values · barriers · surfaces · status · missing).
    very_bad_blocks가 거짓이면 노면 '못 감'을 수동휠체어에서 막지 않고 불확실로 둔다(실측 자료에서 밀어 보기 확인 전)."""
    if mode not in MODES:
        raise ValueError(f"이동 유형은 {MODES} 중 하나: {mode}")
    L = items["len"]
    hi = L if hi is None else hi
    lo, hi = min(lo, hi), max(lo, hi)
    j = Judgement()
    st, closed = items.get("status"), items.get("blocked")
    if st in CLOSED or closed in CLOSED:  # 출입 금지 · 길 아님(구간 확인 결과)
        j.worse("blocked", CLOSED.get(st) or CLOSED[closed])
    elif st == "temp_block" or closed == "temp_block":
        j.notes.append("일시 막힘(안내만)")
    if (st not in ("done", "temp_block") and st not in CLOSED) or items.get("missing"):
        j.worse("uncertain", "구간을 다 재지 못함")
    # 앞뒤 · 좌우: 지나는 범위 ±1 m의 지점, 없으면 가장 가까운 지점
    vals = [x for x in items["values"] if _in(x["s"], lo - 1, hi + 1)]
    if not vals and items["values"]:
        mid = (lo + hi) / 2
        vals = [min(items["values"], key=lambda x: abs(x["s"] - mid))]
    max_long = max_cross = 0.0
    no_cross = 0
    for x in vals:
        if mode in (x.get("uncertain_for") or []):
            j.worse("uncertain", "불확실 표시(저녁 도구)")
        if x.get("long") is not None:
            mag = abs(x["long"])
            max_long = max(max_long, mag)
            r = SLOPE.get(mode)
            if r and _in(mag, *r["unc"]):
                j.worse("uncertain", f"앞뒤 {mag:.1f}°")
            elif r and mag >= r["block"] - EPS:
                j.worse("blocked", f"앞뒤 {mag:.1f}°")
        if x.get("cross") is None:
            no_cross += 1
        else:
            max_cross = max(max_cross, abs(x["cross"]))
    if no_cross:
        j.no_cross = no_cross
        j.notes.append(f"좌우 모름 {no_cross}지점")
    # 장벽
    for x in items["barriers"]:
        t = x["type"]
        if t == "width_rep" or x.get("s") is None:  # 대표 폭, 자리가 빈 기록은 구간 전체에 해당
            hit = True
        else:
            a = x["s"]
            e = x.get("s_end") if x.get("s_end") is not None else a
            a, e = min(a, e), max(a, e)  # 둘째 마디 출발로 잰 이어지는 장벽은 뒤집혀 적힘
            hit = a <= hi + EPS and e >= lo - EPS
        if not hit:
            continue
        if t in BLOCK_TYPES:
            j.worse("blocked", BLOCK_TYPES[t])
        elif t == "bump":
            val = x.get("route_value")
            if val is None or x.get("unmeasured"):
                j.worse("uncertain", "턱 높이 모름")
            elif val > BUMP_UNC[1] + EPS:
                j.worse("blocked", f"턱 {val:g} mm")
            elif val >= BUMP_UNC[0] - EPS or mode in (x.get("uncertain_for") or []):
                j.worse("uncertain", f"턱 {val:g} mm")
        elif t in ("width_rep", "narrow"):
            val = x.get("route_value")
            if val is None:
                if t == "narrow":
                    j.worse("uncertain", "좁은 곳 폭 모름")
            elif val < WIDTH_BLOCK - EPS:
                j.worse("blocked", f"폭 {val:g} cm")
            elif val < WIDTH_UNC - EPS:
                j.worse("uncertain", f"폭 {val:g} cm")
        elif t == "gap":
            if (x.get("dir") or "parallel") != "parallel":  # 직각 틈은 바퀴가 빠지지 않아 보지 않는다(빈 방향·비스듬하면 나란함)
                continue
            rem = x.get("remain_cm")
            if rem is not None and rem >= GAP_AVOID_CM - EPS:
                continue
            val = x.get("value")
            if val is None or x.get("unmeasured"):
                j.worse("uncertain", "틈 폭 모름")
            elif val > GAP_UNC[1] + EPS:
                j.worse("blocked", f"틈 {val:g} mm")
            elif val >= GAP_UNC[0] - EPS:
                j.worse("uncertain", f"틈 {val:g} mm")
        elif t == "temp_block":
            j.notes.append("일시 막힘(안내만)")
    if facility_rules:
        _facility_rules(j, items, mode, lo, hi)
    # 노면: 첫 마디(a)에서 출발해 잰 구간은 각 기록이 자기 s부터 다음 기록 s까지, 둘째 마디(b)에서 출발해 잰 구간
    # (second, 고리 구간 포함 — 저녁 도구가 s = len − 걸은 거리로 바꿈)은 앞 기록 s부터 자기 s까지 덮는다.
    surf = sorted([x for x in items["surfaces"] if x.get("s") is not None], key=lambda x: x["s"])
    surf_pen = 0.0
    for i, x in enumerate(surf):
        if items.get("second"):
            a, e = (surf[i - 1]["s"] if i > 0 else 0.0), x["s"]
        else:
            a, e = x["s"], (surf[i + 1]["s"] if i + 1 < len(surf) else L)
        if e - a < EPS or a > hi + EPS or e < lo - EPS:
            continue
        if x.get("grade") == "very_bad":
            if mode == "manual":
                if very_bad_blocks:
                    j.worse("blocked", "노면 못 감")
                else:
                    j.worse("uncertain", "노면 못 감(밀어 보기로 등급 확인 전)")
            else:
                surf_pen = max(surf_pen, 1.0)
        elif x.get("grade") == "bad":
            surf_pen = max(surf_pen, 0.3)
    pen = 0.2 * max(0.0, max_long - LONG_COST_FROM) + 0.2 * max(0.0, max_cross - CROSS_COST_FROM) + surf_pen
    j.cost = max(hi - lo, 0.01) * (1 + pen)
    return j


# ── 그래프와 길 찾기 ────────────────────────────────────────────────────────
BLOCK_COST = 1e6  # 막힌 구간을 지나야만 할 때, 막힌 구간 수가 가장 적은 길을 찾으려고 더하는 비용


@dataclass
class Ctx:
    segs: dict          # 구간 번호 -> {"a", "b", "len"} (구간표 마디 · 길이)
    items: dict         # 구간 번호 -> 경로 입력의 그 구간 항목(judge가 읽는 모양)
    test: bool = False  # 경로 입력의 test(가상 자료)
    site: str = ""
    surface_checked: bool = False  # 실측 자료에서 밀어 보기로 노면 등급 기준을 확인했는지(CLI --surface-checked)
    facility_rules: bool = False  # 가중치 경로(11/21): 본선 시설 · 진출입부 판정을 켬
    facilities: list = field(default_factory=list)  # 경로 입력의 facilities 전체

    @property
    def very_bad_blocks(self) -> bool:
        """노면 '못 감'으로 수동휠체어를 막는가: 가상 자료(팀 결정)이거나 실측 확인 표시가 있을 때만."""
        return self.test or self.surface_checked


def _edges(ctx, start, goal, mode):
    """(출발 마디, 도착 마디, 구간, s0, s1, 판정) 목록. 출발 · 도착이 있는 구간은 그 점에서 나눈다(같은 구간이면 그 사이도 잇는다)."""
    out = []
    for k, sg in ctx.segs.items():
        if k not in ctx.items:
            continue
        L = sg["len"]
        pts = [(0.0, sg["a"]), (L, sg["b"])]
        for name, (sk, ss) in (("S", start), ("G", goal)):
            if sk != k:
                continue
            ss = min(max(ss, 0.0), L)
            if ss <= EPS or ss >= L - EPS:  # 마디 위면 판정 없는 길이 0 연결만(그 조각을 판정하면 엉뚱하게 막힘)
                out.append((name, sg["a"] if ss <= EPS else sg["b"], k, ss, ss, Judgement(cost=0.0)))
            else:
                pts.append((ss, name))
        pts.sort(key=lambda t: t[0])
        for (s0, n0), (s1, n1) in zip(pts, pts[1:]):
            out.append((n0, n1, k, s0, s1, judge(ctx.items[k], mode, s0, s1, very_bad_blocks=ctx.very_bad_blocks,
                                                 **({"facility_rules": True} if ctx.facility_rules else {}))))
    return out


def _dijkstra(edges, allowed, blocked_cost=None):
    adj = {}
    for e in edges:
        n0, n1, k, s0, s1, j = e
        if j.state not in allowed and blocked_cost is None:
            continue
        c = j.cost + (blocked_cost if j.state == "blocked" and blocked_cost else 0.0)
        adj.setdefault(n0, []).append((n1, c, (k, s0, s1, j)))
        adj.setdefault(n1, []).append((n0, c, (k, s1, s0, j)))
    dist, prev, heap, tie = {"S": 0.0}, {}, [(0.0, 0, "S")], 1
    while heap:
        d, _, u = heapq.heappop(heap)
        if u == "G":
            break
        if d > dist.get(u, float("inf")):
            continue
        for v, c, info in adj.get(u, []):
            nd = d + c
            if nd < dist.get(v, float("inf")) - 1e-12:
                dist[v], prev[v] = nd, (u, info)
                heapq.heappush(heap, (nd, tie, v))
                tie += 1
    if "G" not in dist:
        return None
    path, n = [], "G"
    while n != "S":
        u, info = prev[n]
        path.append((u, n) + info)
        n = u
    return path[::-1]


def _dijkstra_w(edges, allowed, stage3: bool):
    """가중치 길 찾기(11/21): 간선마다 정방향(n0→n1) · 역방향 비용을 따로 둔다.
    stage3이면 막힌 조각도 넣고 (막힌 조각 수, 비용)을 사전식으로 비교한다(지금의 BLOCK_COST 더하기 대신)."""
    adj = {}
    for n0, n1, k, s0, s1, j, cf, bf, cb, bb in edges:
        if j.state not in allowed and not (stage3 and j.state == "blocked"):
            continue
        nb = 1 if j.state == "blocked" else 0
        adj.setdefault(n0, []).append((n1, nb, cf, (k, s0, s1, j, cf, bf)))
        adj.setdefault(n1, []).append((n0, nb, cb, (k, s1, s0, j, cb, bb)))
    dist, prev, heap, tie = {"S": (0, 0.0)}, {}, [((0, 0.0), 0, "S")], 1
    while heap:
        d, _, u = heapq.heappop(heap)
        if u == "G":
            break
        if d > dist.get(u, (float("inf"), float("inf"))):
            continue
        for v, nb, c, info in adj.get(u, []):
            nd = (d[0] + nb, d[1] + c)
            od = dist.get(v)
            if od is None or nd[0] < od[0] or (nd[0] == od[0] and nd[1] < od[1] - 1e-12):
                dist[v], prev[v] = nd, (u, info)
                heapq.heappush(heap, (nd, tie, v))
                tie += 1
    if "G" not in dist:
        return None
    path, n = [], "G"
    while n != "S":
        u, info = prev[n]
        path.append((u, n) + info)
        n = u
    return path[::-1]


def _find_route_w(ctx, start, goal, mode, cost_fn):
    edges = []
    for n0, n1, k, s0, s1, j in _edges(ctx, start, goal, mode):
        if abs(s1 - s0) < EPS:
            cf = cb = (0.0, {})
        else:
            it = ctx.items[k]
            cf, cb = cost_fn(it, mode, s0, s1, True, j), cost_fn(it, mode, s0, s1, False, j)
        edges.append((n0, n1, k, s0, s1, j, cf[0], cf[1], cb[0], cb[1]))
    status, path = "ok", _dijkstra_w(edges, {"ok"}, False)
    if path is None:
        status, path = "uncertain", _dijkstra_w(edges, {"ok", "uncertain"}, False)
    if path is None:
        status, path = "none", _dijkstra_w(edges, {"ok", "uncertain"}, True)
    steps, notes, no_cross, total, bd = [], [], 0, 0.0, {}
    for n0, n1, k, s0, s1, j, c, b in path or []:
        if abs(s1 - s0) < EPS:
            continue
        no_cross += j.no_cross
        total += c
        for key, x in b.items():
            bd[key] = bd.get(key, 0.0) + x
        steps.append({"seg": k, "n0": n0, "n1": n1, "s0": round(s0, 3), "s1": round(s1, 3), "state": j.state,
                      "reasons": j.reasons, "cost": round(c, 3)})
        notes += [n for n in j.notes if n not in notes and not n.startswith("좌우 모름")]
    if no_cross:
        notes.append(f"좌우 모름 {no_cross}지점")
    return {
        "found": status != "none",
        "status": status,
        "length_m": round(sum(abs(x["s1"] - x["s0"]) for x in steps), 3),
        "steps": steps,
        "uncertain_segs": sum(1 for x in steps if x["state"] == "uncertain"),
        "blocked_by": [{"seg": x["seg"], "reasons": x["reasons"]} for x in steps if x["state"] == "blocked"]
        if status == "none" else [],
        "notes": notes if path is not None else notes + ["연결된 길 없음"],
        "cost": round(total, 3),
        "breakdown": {key: round(x, 3) for key, x in bd.items()},
    }


def find_route(ctx: Ctx, start: tuple, goal: tuple, mode: str, cost_fn=None) -> dict:
    """start · goal = (구간 번호, s). 1차는 갈 수 있음만, 2차는 불확실까지, 그래도 없으면 막힌 구간 수가 가장 적은 길로 이유를 돌려준다.
    cost_fn(route_cost.make_cost_fn)을 주면 방향 있는 가중치 비용으로 찾고 결과에 cost · breakdown을 더한다(11/21)."""
    for k, _ in (start, goal):
        if k not in ctx.items:
            raise ValueError(f"경로 입력에 없는 구간: {k}")
    if cost_fn is not None:
        return _find_route_w(ctx, start, goal, mode, cost_fn)
    edges = _edges(ctx, start, goal, mode)
    status, path = "ok", _dijkstra(edges, {"ok"})
    if path is None:
        status, path = "uncertain", _dijkstra(edges, {"ok", "uncertain"})
    if path is None:
        status, path = "none", _dijkstra(edges, {"ok", "uncertain"}, BLOCK_COST)
    steps, notes, no_cross = [], [], 0
    for n0, n1, k, s0, s1, j in path or []:
        if abs(s1 - s0) < EPS:
            continue
        no_cross += j.no_cross
        steps.append({"seg": k, "n0": n0, "n1": n1, "s0": round(s0, 3), "s1": round(s1, 3), "state": j.state,
                      "reasons": j.reasons, "cost": round(j.cost, 3)})
        notes += [n for n in j.notes if n not in notes and not n.startswith("좌우 모름")]
    if no_cross:
        notes.append(f"좌우 모름 {no_cross}지점")
    return {
        "found": status != "none",
        "status": status,
        "length_m": round(sum(abs(x["s1"] - x["s0"]) for x in steps), 3),
        "steps": steps,
        "uncertain_segs": sum(1 for x in steps if x["state"] == "uncertain"),
        "blocked_by": [{"seg": x["seg"], "reasons": x["reasons"]} for x in steps if x["state"] == "blocked"]
        if status == "none" else [],
        "notes": notes if path is not None else notes + ["연결된 길 없음"],
    }


# ── 실제 자료 읽기 · 시설 이름으로 찾기 · CLI ─────────────────────────────────

RESULT_FORMAT = "bf-route-result-1"


def load(route_input, pack, facilities, surface_checked=False, facility_rules=False):
    """경로 입력(bf-route-input-1) · 구간표(pack) · 시설 목록(geojson)을 읽는다. 대상지와 상관없음."""
    rd = lambda f: json.loads(pathlib.Path(f).read_text(encoding="utf-8"))
    ri, pk, fc = rd(route_input), rd(pack), rd(facilities)
    segs = {s["seg"]: {"a": s["a"], "b": s["b"], "len": s["len"], "xy": s.get("xy", [])} for s in pk["segs"]}
    items = {}
    for s in ri["segments"]:
        k = s["seg"]
        if k not in segs:
            continue
        items[k] = {"seg": k, "len": segs[k]["len"], "status": s.get("status"), "missing": s.get("missing") or [],
                    "blocked": s.get("blocked"), "second": bool(s.get("second")), "values": [], "barriers": [], "surfaces": [],
                    "facilities": []}
    for key, name in (("values", "values"), ("barriers", "barriers"), ("surfaces", "surfaces"), ("facilities", "facilities")):
        for x in ri.get(key, []):
            if x.get("seg") in items:
                items[x["seg"]][name].append(x)
    facs = []
    for f in fc["features"]:
        d = dict(f["properties"])
        d["lon"], d["lat"] = f["geometry"]["coordinates"][:2]
        facs.append(d)
    return Ctx(segs=segs, items=items, test=bool(ri.get("test")), site=ri.get("site", ""), surface_checked=surface_checked,
               facility_rules=facility_rules, facilities=list(ri.get("facilities", []))), facs


def _project_px(xy, L, px):
    """구간표 선(xy, 항공사진 픽셀)에 점을 투영해 구간 길이 단위 s를 돌려준다."""
    pts = [(xy[i], xy[i + 1]) for i in range(0, len(xy) - 1, 2)]
    if len(pts) < 2:
        return L / 2
    acc, best, total = 0.0, (float("inf"), 0.0), 0.0
    seglens = [math.dist(a, b) for a, b in zip(pts, pts[1:])]
    total = sum(seglens) or 1.0
    for (a, b), d in zip(zip(pts, pts[1:]), seglens):
        t = 0.0 if d < 1e-9 else max(0.0, min(1.0, ((px[0] - a[0]) * (b[0] - a[0]) + (px[1] - a[1]) * (b[1] - a[1])) / (d * d)))
        q = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        dist = math.dist(q, px)
        if dist < best[0]:
            best = (dist, acc + d * t)
        acc += d
    return best[1] / total * L


def facility_point(ctx, facs, key):
    """시설 이름(정확히)이나 번호로 시설을 찾아 (시설, 구간, s)를 돌려준다."""
    hit = [f for f in facs if f.get("name") == key or str(f.get("no")) == str(key)]
    if not hit:
        raise ValueError(f"시설 목록에 없음: {key}")
    f = hit[0]
    k = f.get("seg")
    if k not in ctx.items:
        raise ValueError(f"시설 '{f.get('name')}'의 구간 {k}이(가) 경로 입력에 없음")
    sg = ctx.segs[k]
    return f, k, round(_project_px(sg["xy"], sg["len"], f["aerial_px"]), 3)


def route_by_names(ctx, facs, from_key, to_key, mode):
    f0, k0, s0 = facility_point(ctx, facs, from_key)
    f1, k1, s1 = facility_point(ctx, facs, to_key)
    r = find_route(ctx, (k0, s0), (k1, s1), mode)

    def pt(f, k, s):
        d = {"name": f.get("name"), "no": f.get("no"), "seg": k, "s": s}
        if f.get("src"):  # 시설 목록에 출처 칸이 있을 때만(민속촌 목록에는 없음)
            d["src"] = f["src"]
        return d

    # 출발·도착 자리가 가상이면(제주대 계단 없는 출입구 등) 결과에 드러낸다(11/15 팀 결정)
    virtual = [f"{label} '{f.get('name')}' 자리는 {f['src']}, 실측 전"
               for label, f in (("출발", f0), ("도착", f1)) if str(f.get("src") or "").startswith("가상")]
    return {"format": RESULT_FORMAT, "site": ctx.site, "test": ctx.test, "mode": mode,
            "from": pt(f0, k0, s0), "to": pt(f1, k1, s1), **r, "notes": r["notes"] + virtual}


# ── 가중치 경로(11/21): 세 길 · 같은 길 표시 · 출입구 확인 ─────────────────────
RESULT_FORMAT2 = "bf-route-result-2"
ROUTE_KEYS = ("fast", "comfort", "safe")
ROUTE_KO = {"fast": "빠른 길", "comfort": "편한 길", "safe": "안전한 길"}
ENTRY_NA_TYPES = {"구역", "출입", "bus_stop", "gate"}  # 실외 · 출입 지점: 출입구 확인 해당 없음
UNNAMED_DOORS = ("출입구", "건물 출입구")


def _ranges(r):
    out = {}
    for x in r["steps"]:
        a, e = sorted((x["s0"], x["s1"]))
        if e - a > EPS:
            out.setdefault(x["seg"], []).append([a, e])
    for k, rs in out.items():  # 같은 구간 안 범위 합치기
        rs.sort()
        m = [rs[0]]
        for a, e in rs[1:]:
            if a <= m[-1][1] + EPS:
                m[-1][1] = max(m[-1][1], e)
            else:
                m.append([a, e])
        out[k] = m
    return out


def route_overlap(ra: dict, rb: dict) -> float:
    """두 길이 겹치는 길이 / 긴 쪽 길이(0~1, 2자리). 둘 다 길이 0이면 1.0, 한쪽만 0이면 0.0."""
    la, lb = ra.get("length_m", 0.0), rb.get("length_m", 0.0)
    if la < EPS and lb < EPS:
        return 1.0
    if la < EPS or lb < EPS:
        return 0.0
    A, B = _ranges(ra), _ranges(rb)
    common = 0.0
    for k in A.keys() & B.keys():
        for a0, a1 in A[k]:
            for b0, b1 in B[k]:
                common += max(0.0, min(a1, b1) - max(a0, b0))
    return round(common / max(la, lb), 2)


def _path_key(r):
    return [(x["seg"], x["s0"], x["s1"]) for x in r["steps"]]


def _rescore(ctx, r, mode, w) -> float:
    """찾은 길을 다른 가중치로 다시 매긴 벌점 합(m). 세 길을 같은 잣대로 비교하려고(최종 검토 11/21)."""
    tot = 0.0
    for x in r["steps"]:
        _, bd = RC.piece_cost(ctx.items[x["seg"]], mode, x["s0"], x["s1"], x["s1"] >= x["s0"], Judgement(state=x["state"]), w)
        tot += sum(bd.values())
    return round(tot, 1)


def three_routes(ctx, start, goal, mode, weights, personal=None) -> dict:
    """빠른 · 편한 · 안전한 길을 같은 판정 · 단계 찾기로 찾고, 같은 길이면 same_as, 겹침 비율은 overlap에 적는다."""
    out = {}
    for key in ROUTE_KEYS:
        w = RC.effective(weights, key, mode, personal)
        out[key] = find_route(ctx, start, goal, mode, cost_fn=RC.make_cost_fn(w))
    for i, key in enumerate(ROUTE_KEYS):
        r = out[key]
        r["same_as"] = next((k for k in ROUTE_KEYS[:i] if _path_key(out[k]) == _path_key(r)), None)
        r["overlap"] = {k: route_overlap(r, out[k]) for k in ROUTE_KEYS if k != key}
        r["compare"] = {k: _rescore(ctx, r, mode, RC.effective(weights, k, mode, personal)) for k in ("comfort", "safe")}
    return out


def _door_state(rec, recs, mode):
    """출입구 · 화장실 기록 하나의 (판정, 이유)."""
    j = Judgement()
    if rec.get("steps_before"):
        rp = [x for x in recs if x.get("type") == "ramp" and x.get("dest") == "door" and x.get("seg") == rec.get("seg")
              and x.get("name") == rec.get("name")]
        if not rp:
            j.worse("blocked", "문 앞 계단")
        else:
            sl = [abs(x) for x in (rp[0].get(k) for k in ("slope_low", "slope_mid", "slope_top")) if x is not None]
            if not sl:
                j.worse("uncertain", "문으로 가는 경사로, 기울기 모름")
            else:
                st = _slope_state(max(sl), mode)
                if st:
                    j.worse(st, f"문으로 가는 경사로 {max(sl):.1f}°")
            st = _width_state(rp[0].get("w_cm"))
            if st:
                j.worse(st, f"문으로 가는 경사로 폭 {rp[0]['w_cm']:g} cm")
    sill = rec.get("bump_mm") if rec.get("type") == "toilet" else rec.get("sill_mm")
    if sill is None:
        j.worse("uncertain", "문턱 모름")
    else:
        st = _bump_state(sill)
        if st:
            j.worse(st, f"문턱 {sill:g} mm")
    cm = rec.get("door_cm")
    if cm is None:
        j.worse("uncertain", "문 폭 모름")
    else:
        st = _width_state(cm)
        if st:
            j.worse(st, f"문 폭 {cm:g} cm")
    if rec.get("type") == "toilet" and str(rec.get("stall")).lower() in ("no", "none", "없음"):
        j.worse("blocked", "장애인 칸 없음")
    return j


def entry_for(ctx, fac: dict, k, s, mode: str) -> dict:
    """목적지 출입구 확인(설계 3장 다, 줄인 안). 길 찾기는 바꾸지 않고 결과에 붙여 보여 주기만 한다."""
    out = {"state": "na", "door": None, "reasons": [], "candidates": 0, "notes": []}
    if fac.get("type") in ENTRY_NA_TYPES:
        return out
    recs = ctx.facilities
    kinds = {"entrance", "toilet"} if fac.get("type") == "화장실" else {"entrance"}
    cand = [x for x in recs if x.get("type") in kinds and x.get("name") == fac.get("name")]
    unnamed = False
    if not cand:
        cand = [x for x in recs if x.get("type") in kinds and x.get("name") in UNNAMED_DOORS and x.get("seg") == k]
        unnamed = bool(cand)
    if not cand:
        return out | {"state": "unknown", "reasons": ["출입구 기록 없음"]}

    def dist(x):
        return (0, abs((x.get("s") or 0.0) - s)) if x.get("seg") == k else (1, 0.0)

    cand.sort(key=dist)
    judged = [(x, _door_state(x, recs, mode)) for x in cand]
    near, jn = judged[0]
    reasons = list(jn.reasons) + (["이름 없는 출입구, 같은 구간으로 찾음"] if unnamed else [])
    best, jb = min(judged, key=lambda t: RANK[t[1].state])
    if RANK[jb.state] < RANK[jn.state]:
        d = dist(best)
        reasons.append(f"더 나은 출입구: {best.get('name')}" + (f"(약 {d[1]:.0f} m)" if d[0] == 0 else "(다른 구간)"))
    notes = ["요청하면 열림"] if near.get("lock") == "ask" else []
    return {"state": jn.state, "door": {"name": near.get("name"), "seg": near.get("seg"), "s": near.get("s")},
            "reasons": reasons, "candidates": len(cand), "notes": notes}


def route3_by_names(ctx, facs, from_key, to_key, mode, weights, personal=None) -> dict:
    f0, k0, s0 = facility_point(ctx, facs, from_key)
    f1, k1, s1 = facility_point(ctx, facs, to_key)
    routes = three_routes(ctx, (k0, s0), (k1, s1), mode, weights, personal)

    def pt(f, k, s):
        d = {"name": f.get("name"), "no": f.get("no"), "seg": k, "s": s}
        if f.get("src"):
            d["src"] = f["src"]
        return d

    virtual = [f"{label} '{f.get('name')}' 자리는 {f['src']}, 실측 전"
               for label, f in (("출발", f0), ("도착", f1)) if str(f.get("src") or "").startswith("가상")]
    return {"format": RESULT_FORMAT2, "site": ctx.site, "test": ctx.test, "mode": mode,
            "from": pt(f0, k0, s0), "to": pt(f1, k1, s1), "weights_version": weights.get("version"),
            "routes": routes, "entry": entry_for(ctx, f1, k1, s1, mode), "notes": virtual}


def as_v1(r2: dict, key: str) -> dict:
    """세 길 결과에서 한 길을 bf-route-result-1 모양으로(Unity RouteView가 그대로 읽음)."""
    x = r2["routes"][key]
    return {"format": RESULT_FORMAT, "site": r2["site"], "test": r2["test"], "mode": r2["mode"],
            "from": r2["from"], "to": r2["to"], "route": key,
            **{k: x[k] for k in ("found", "status", "length_m", "steps", "uncertain_segs", "blocked_by")},
            "notes": x["notes"] + [n for n in r2["notes"] if n not in x["notes"]]}


def _main_three(a, ctx, facs):
    wt = RC.load_weights(a.weights)
    personal = json.loads(a.personal) if a.personal else None
    r = route3_by_names(ctx, facs, a.src, a.dst, a.mode, wt, personal)
    out = pathlib.Path(a.out) if a.out else \
        pathlib.Path(a.input).parent / "경로" / f"경로3_{r['from']['no']}_{r['to']['no']}_{a.mode}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    for key in ROUTE_KEYS:
        (out.parent / f"{out.stem}_{key}.json").write_text(json.dumps(as_v1(r, key), ensure_ascii=False, indent=1),
                                                          encoding="utf-8")
    tag = " (가상 자료)" if r["test"] else ""
    print(f"{r['from']['name']} → {r['to']['name']} · {a.mode}{tag}")
    for key in ROUTE_KEYS:
        x = r["routes"][key]
        why = f"부담 +{x['compare']['comfort']:.0f} m · 위험 +{x['compare']['safe']:.0f} m(세 길 같은 기준)"
        same = f" ({ROUTE_KO[x['same_as']]}과 같음)" if x["same_as"] else ""
        print(f"  {ROUTE_KO[key]}: {x['status']}, {x['length_m']:.0f} m, 비용 {x['cost']:.0f}{same} — {why}")
    e = r["entry"]
    print(f"  출입구: {e['state']}" + (f" — {', '.join(e['reasons'])}" if e["reasons"] else ""))
    print(f"저장: {out} (+ 길마다 _fast · _comfort · _safe)")


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="경로 추천 앱 첫 판(다익스트라 기본판)")
    ap.add_argument("--input", required=True, help="경로 입력 파일(bf-route-input-1)")
    ap.add_argument("--pack", required=True, help="측정 앱 구간표(pack)")
    ap.add_argument("--facilities", required=True, help="시설목록.geojson")
    ap.add_argument("--from", dest="src")
    ap.add_argument("--to", dest="dst")
    ap.add_argument("--mode", choices=MODES, default="manual")
    ap.add_argument("--out")
    ap.add_argument("--list", action="store_true", help="시설 목록만 보여 줌")
    ap.add_argument("--surface-checked", action="store_true", help="실측 자료: 밀어 보기로 노면 등급 기준을 확인함('못 감'으로 수동휠체어를 막음)")
    ap.add_argument("--three", action="store_true", help="가중치 경로(11/21): 빠른 · 편한 · 안전한 길과 출입구 확인(시설 판정 켬)")
    ap.add_argument("--weights", default=str(pathlib.Path(__file__).resolve().parent / "route_weights.json"))
    ap.add_argument("--personal", help='사람별 배수 JSON, 예: {"long": 2}')
    a = ap.parse_args(argv)
    ctx, facs = load(a.input, a.pack, a.facilities, a.surface_checked, facility_rules=a.three)
    if a.list:
        for f in facs:
            print(f"{f.get('no'):>3} {f.get('name')} (구간 {f.get('seg')})")
        return
    if not (a.src and a.dst):
        ap.error("--from과 --to가 필요합니다(--list로 시설을 볼 수 있음)")
    if a.three:
        return _main_three(a, ctx, facs)
    r = route_by_names(ctx, facs, a.src, a.dst, a.mode)
    out = pathlib.Path(a.out) if a.out else pathlib.Path(a.input).parent / "경로" / f"경로_{r['from']['no']}_{r['to']['no']}_{a.mode}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    tag = " (가상 자료)" if r["test"] else ""
    print(f"{r['from']['name']} → {r['to']['name']} · {a.mode}: {r['status']}, {r['length_m']:.0f} m, 불확실 구간 {r['uncertain_segs']}{tag}")
    for x in r["blocked_by"]:
        print(f"  막힘: 구간 {x['seg']} — {', '.join(x['reasons'])}")
    for n in r["notes"]:
        if "자리는 가상" in n:
            print(f"  안내: {n}")
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
