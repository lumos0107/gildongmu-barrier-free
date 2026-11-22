"""앱 길찾기용 길 그래프 내보내기와 파이썬 기준 구현(B단계 Task 2, 2026-11-22).
계획 Docs/2026-11-22-B단계-작업계획.md. 앱 안 자바스크립트(router.js)가 엔진과 같은 세 길을 다시 찾을 수 있게,
조각마다 유형별 판정과 가중치 곱하기 전 벌점 항(엔진이 더하는 순서 그대로)을 내보낸다.
ref_three는 그 자료만으로 엔진의 _dijkstra_w를 돌려 엔진과 같은지 확인하는 기준 구현이다.
"""
import pathlib
import sys
from dataclasses import replace

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import route_cost as RC  # noqa: E402
import route_engine as R  # noqa: E402

FORMAT = "bf-route-graph-1"
EPS = R.EPS
# 세 묶음(팀 결정 2026-11-22)과 키 · 단계 배수(구현 설정). uncertain · cross_unknown은 조절하지 않는다.
GROUPS = {"slope": ("long", "cross", "fac_slope", "climb_no_rest"),
          "floor": ("surface_bad", "surface_very_bad", "bump_low", "narrow_len", "narrow_point", "narrow_point_long"),
          "road": ("shared", "drop", "drop_open", "driveway")}
LEVELS = {"less": 0.5, "normal": 1.0, "more": 2.0}


def personal_of(levels: dict) -> dict:
    """{'slope': 'more', …} → 사람별 배수 {키: 배수}(빠진 묶음은 보통)."""
    return {k: LEVELS[levels.get(g, "normal")] for g, keys in GROUPS.items() for k in keys}


def piece_terms(items, lo, hi, forward, w) -> list:
    """조각의 벌점 항 [(키, 값)](가중치 곱하기 전, 0은 뺌, 'uncertain' 뺌). w는 진출입부 예외(좌우 계수 > 0)에만 쓰인다."""
    t = []
    RC.piece_cost(items, "manual", lo, hi, forward, R.Judgement(state="ok"), w, terms=t)
    return [(k, x) for k, x in t if x != 0]


def pick_terms(t, t0, w):
    """좌우 계수가 0이면 진출입부 항이 다른 목록(t0, 있을 때만)을 쓴다."""
    return t0 if t0 is not None and not w.get("cross", 0.0) > 0 else t


def cost_from(terms, state, length, w) -> tuple:
    """route_cost.piece_cost와 같은 순서로: 항마다 계수 곱 → EPS 거르기 → 키별 합(처음 나온 순서) → 6자리 → 길이 + 합."""
    length = abs(length)
    if length < EPS:
        return 0.0, {}
    bd = {}
    for k, x in list(terms) + ([("uncertain", 1)] if state == "uncertain" else []):
        v = x * w.get(k, 0.0)
        if v > EPS:
            bd[k] = bd.get(k, 0.0) + v
    bd = {k: round(v, 6) for k, v in bd.items()}
    return length + sum(bd.values()), bd


def _terms_pair(items, s0, s1, forward):
    t = piece_terms(items, s0, s1, forward, {"cross": 1.0})
    t0 = piece_terms(items, s0, s1, forward, {"cross": 0.0})
    return [list(x) for x in t], ([list(x) for x in t0] if t0 != t else None)


def export_graph(ctx, facs, start_name, weights) -> dict:
    _, ks, ss = R.facility_point(ctx, facs, start_name)
    goals = {}
    for f in facs:
        if f["name"] != start_name:
            _, k, s = R.facility_point(ctx, facs, f["name"])
            goals[f["name"]] = [k, s]
    return graph_from_points(ctx, (ks, ss), goals, weights)


def graph_from_points(ctx, start, goals: dict, weights) -> dict:
    """출발 (구간, s)과 도착 {이름: [구간, s]}으로 그래프 자료를 만든다(시설 목록 없이 쓰는 작은 시험 자료용으로도)."""
    ks, ss = start
    judg = {}  # (k, s0, s1) -> {유형: [state, reasons]}, 넣은 순서 = 통째 조각(구간 순서) 다음 나뉜 조각

    def take(edges, mode):
        for _, _, k, s0, s1, j in edges:
            if abs(s1 - s0) >= EPS:
                judg.setdefault((k, s0, s1), {}).setdefault(mode, [j.state, list(j.reasons)])
    for mode in R.MODES:  # 통째 조각: 출발 · 도착이 없는 구간처럼(_edges를 그대로 써서 판정 인자가 엔진과 같음)
        take(R._edges(ctx, (None, 0.0), (None, 0.0), mode), mode)
    for g in goals.values():  # 나뉜 조각: 출발 · 그 도착이 있는 구간만 넣은 ctx로 _edges
        sub = replace(ctx, segs={k: ctx.segs[k] for k in dict.fromkeys((ks, g[0]))})
        for mode in R.MODES:
            take(R._edges(sub, (ks, ss), tuple(g), mode), mode)
    pieces = []
    for (k, s0, s1), jm in judg.items():
        it = ctx.items[k]
        tf, tf0 = _terms_pair(it, s0, s1, True)
        tb, tb0 = _terms_pair(it, s0, s1, False)
        pieces.append([k, s0, s1, jm, tf, tb, tf0, tb0])
    return {"format": FORMAT, "site": ctx.site, "segs": [[k, sg["a"], sg["b"], sg["len"]] for k, sg in ctx.segs.items() if k in ctx.items],
            "start": [ks, ss], "goals": {n: list(g) for n, g in goals.items()}, "pieces": pieces, "weights": weights,
            "keys": list(RC.KEYS), "groups": {g: list(k) for g, k in GROUPS.items()}, "levels": LEVELS}


def unstable_s(G) -> list:
    """3자리로 반올림하면 값이 바뀌는 조각 s 목록 [(구간, s0, s1)]. 앱은 엔진 결과의 3자리 s로 조각 그림 선을 찾으므로
    하나라도 있으면 선을 못 찾는다(B단계 최종 검토 미룬 것, 2026-11-22). build_shell이 이것이 비어 있지 않으면 멈춘다."""
    return [(p[0], p[1], p[2]) for p in G["pieces"] if round(p[1], 3) != p[1] or round(p[2], 3) != p[2]]


# ── 파이썬 기준 구현: 내보낸 자료만으로 엔진의 단계 찾기를 돌린다 ───────────────────

def _index(G):
    if "_idx" not in G:
        G["_idx"] = {(p[0], p[1], p[2]): p for p in G["pieces"]}
    return G["_idx"]


def _edges_from(G, start, goal, mode, w):
    P, out = _index(G), []
    for k, a, b, L in G["segs"]:
        pts = [(0.0, a), (L, b)]
        for name, (sk, ss) in (("S", start), ("G", goal)):
            if sk != k:
                continue
            ss = min(max(ss, 0.0), L)
            if ss <= EPS or ss >= L - EPS:
                out.append((name, a if ss <= EPS else b, k, ss, ss, R.Judgement(cost=0.0), 0.0, {}, 0.0, {}))
            else:
                pts.append((ss, name))
        pts.sort(key=lambda t: t[0])
        for (s0, n0), (s1, n1) in zip(pts, pts[1:]):
            p = P[(k, s0, s1)]
            st, rs = p[3][mode]
            cf = cost_from(pick_terms(p[4], p[6], w), st, s1 - s0, w)
            cb = cost_from(pick_terms(p[5], p[7], w), st, s1 - s0, w)
            out.append((n0, n1, k, s0, s1, R.Judgement(state=st, reasons=list(rs)), cf[0], cf[1], cb[0], cb[1]))
    return out


def _find(G, start, goal, mode, w):
    edges = _edges_from(G, start, goal, mode, w)
    status, path = "ok", R._dijkstra_w(edges, {"ok"}, False)
    if path is None:
        status, path = "uncertain", R._dijkstra_w(edges, {"ok", "uncertain"}, False)
    if path is None:
        status, path = "none", R._dijkstra_w(edges, {"ok", "uncertain"}, True)
    steps, total, raw = [], 0.0, []
    for n0, n1, k, s0, s1, j, c, b in path or []:
        if abs(s1 - s0) < EPS:
            continue
        total += c
        raw.append((k, s0, s1, j.state))
        steps.append({"seg": k, "n0": n0, "n1": n1, "s0": round(s0, 3), "s1": round(s1, 3), "state": j.state,
                      "reasons": j.reasons, "cost": round(c, 3)})
    return {"found": status != "none", "status": status, "length_m": round(sum(abs(x["s1"] - x["s0"]) for x in steps), 3),
            "steps": steps, "uncertain_segs": sum(1 for x in steps if x["state"] == "uncertain"),
            "blocked_by": [{"seg": x["seg"], "reasons": x["reasons"]} for x in steps if x["state"] == "blocked"]
            if status == "none" else [], "cost": round(total, 3), "_raw": raw}


def _rescore(G, raw, w) -> float:
    P, tot = _index(G), 0.0
    for k, s0, s1, st in raw:
        p = P[(k, min(s0, s1), max(s0, s1))]
        t = pick_terms(p[4], p[6], w) if s1 >= s0 else pick_terms(p[5], p[7], w)
        tot += sum(cost_from(t, st, s1 - s0, w)[1].values())
    return round(tot, 1)


def ref_three(G, goal, mode, weights, personal=None) -> dict:
    start, gp = tuple(G["start"]), tuple(G["goals"][goal])
    W = {rk: RC.effective(weights, rk, mode, personal) for rk in R.ROUTE_KEYS}
    out = {rk: _find(G, start, gp, mode, W[rk]) for rk in R.ROUTE_KEYS}
    for i, rk in enumerate(R.ROUTE_KEYS):
        r = out[rk]
        r["same_as"] = next((k for k in R.ROUTE_KEYS[:i] if R._path_key(out[k]) == R._path_key(r)), None)
        r["compare"] = {k: _rescore(G, r["_raw"], W[k]) for k in ("comfort", "safe")}
    for r in out.values():
        r.pop("_raw")
    return out
