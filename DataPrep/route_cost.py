"""가중치 경로(2026-11-21): 길 조각 하나의 비용 = 거리 + 항목별 벌점('더 걷는 미터').
설계: Docs/2026-11-21-가중치경로-설계.md 3장 나 · 계획: Docs/2026-11-21-가중치경로-작업계획.md Task 2.
판정(막힘 · 불확실)은 route_engine.judge가 맡고, 여기서는 받은 판정을 바꾸지 않는다.
"""
import json
import math
import pathlib

EPS = 1e-9
KEYS = ("long", "cross", "surface_bad", "surface_very_bad", "fac_slope", "bump_low", "narrow_len", "narrow_point",
        "narrow_point_long", "climb_no_rest", "shared", "drop", "drop_open", "driveway", "uncertain", "cross_unknown")
LABEL_KO = {"long": "앞뒤 경사", "cross": "좌우 기울기", "surface_bad": "거친 노면", "surface_very_bad": "못 감 노면",
            "fac_slope": "급한 경사로", "bump_low": "낮은 턱", "narrow_len": "좁은 길(비켜설 곳 없음)",
            "narrow_point": "좁은 곳", "narrow_point_long": "길게 좁은 곳", "climb_no_rest": "쉴 곳 없는 긴 오르막",
            "shared": "차량과 함께 쓰는 길", "drop": "낙차 옆", "drop_open": "난간 없는 낙차 쪽 기울기",
            "driveway": "차량 진출입부", "uncertain": "확인 안 된 구간", "cross_unknown": "좌우 기울기 모름"}
ROUTES = ("fast", "comfort", "safe")
MODES = ("manual", "power", "stroller")
LONG_FROM, CROSS_FROM = 3.2, 2.3   # 1/18, 1/25 (측정 매뉴얼 기준 환산표)
BUMP_LOW = (13, 17)                # 매뉴얼 기록 시작 13 mm, 18~22는 판정이 불확실로 처리
WIDE_CM = 150                      # 매뉴얼 비켜설 곳 기준 1.5 m
CLIMB_M = 30                       # 매뉴얼 쉬는 평지: 3.2° 이상이 30 m 넘게
REST_NEAR_M = 2


def _num(x, where):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0:
        raise ValueError(f"가중치는 0 이상 유한한 수여야 함: {where} = {x!r}")
    return float(x)


def _check_map(d, where):
    for k, x in (d or {}).items():
        if k not in KEYS:
            raise ValueError(f"모르는 가중치 키: {where}.{k}")
        _num(x, f"{where}.{k}")


def load_weights(path) -> dict:
    wt = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    for r, d in wt.get("routes", {}).items():
        if r not in ROUTES:
            raise ValueError(f"모르는 길 이름: {r}")
        _check_map(d, f"routes.{r}")
    for m, d in wt.get("mode_mult", {}).items():
        if m not in MODES:
            raise ValueError(f"모르는 이동 유형: {m}")
        _check_map(d, f"mode_mult.{m}")
    for k in wt.get("why", {}):
        if k not in KEYS:
            raise ValueError(f"모르는 근거 키: why.{k}")
    return wt


def effective(weights: dict, route: str, mode: str, personal: dict | None = None) -> dict:
    """길 · 이동 유형 · 사람별 배수를 곱한 실제 계수(모든 키)."""
    base = weights.get("routes", {}).get(route, {})
    mult = weights.get("mode_mult", {}).get(mode, {})
    _check_map(base, f"routes.{route}")
    _check_map(mult, f"mode_mult.{mode}")
    _check_map(personal, "personal")
    personal = personal or {}
    return {k: float(base.get(k, 0.0)) * float(mult.get(k, 1.0)) * float(personal.get(k, 1.0)) for k in KEYS}


# ── 자료에서 범위 · 점 뽑기 ───────────────────────────────────────────────────

def _overlap(a, e, lo, hi):
    a, e = min(a, e), max(a, e)
    return max(0.0, min(e, hi) - max(a, lo))


def _cover(points, L):
    """측정 지점이 이웃과의 가운데까지 덮는다. [(a, e, 지점)] (0~L을 나눔)."""
    pts = sorted(points, key=lambda x: x["s"])
    out = []
    for i, x in enumerate(pts):
        a = 0.0 if i == 0 else (pts[i - 1]["s"] + x["s"]) / 2
        e = L if i == len(pts) - 1 else (x["s"] + pts[i + 1]["s"]) / 2
        out.append((a, e, x))
    return out


def _value_at(cover, s):
    for a, e, x in cover:
        if a - EPS <= s <= e + EPS:
            return x
    return None


def _surface_spans(items):
    """judge와 같은 노면 덮는 규칙: 첫 마디 출발은 자기 s부터 다음 s까지, 둘째 마디 출발은 앞 s부터 자기 s까지."""
    L = items["len"]
    surf = sorted([x for x in items.get("surfaces", []) if x.get("s") is not None], key=lambda x: x["s"])
    out = []
    for i, x in enumerate(surf):
        if items.get("second"):
            a, e = (surf[i - 1]["s"] if i > 0 else 0.0), x["s"]
        else:
            a, e = x["s"], (surf[i + 1]["s"] if i + 1 < len(surf) else L)
        out.append((a, e, x.get("grade")))
    return out


def _in_closed(s, lo, hi):
    return s is not None and lo - EPS <= s <= hi + EPS


def piece_cost(items, mode, lo, hi, forward, j, w) -> tuple:
    """조각 [lo, hi] (forward면 lo→hi로 지남)의 (비용, 항목별 벌점). 비용 = (hi − lo) + 벌점 합. j는 바꾸지 않는다."""
    lo, hi = min(lo, hi), max(lo, hi)
    length = hi - lo
    if length < EPS:
        return 0.0, {}
    L = items["len"]
    bd = {}

    def add(k, x):
        x = x * w.get(k, 0.0)
        if x > EPS:
            bd[k] = bd.get(k, 0.0) + x

    vals = [x for x in items.get("values", []) if x.get("s") is not None]
    longc = _cover([x for x in vals if x.get("long") is not None], L)
    crossc = _cover([x for x in vals if x.get("cross") is not None], L)
    for a, e, x in longc:
        add("long", max(0.0, abs(x["long"]) - LONG_FROM) * _overlap(a, e, lo, hi))
    for a, e, x in crossc:
        add("cross", max(0.0, abs(x["cross"]) - CROSS_FROM) * _overlap(a, e, lo, hi))
    add("cross_unknown", sum(1 for x in vals if x.get("cross") is None and _in_closed(x["s"], lo, hi)))

    # 쉴 곳 없는 긴 오르막(진행 방향으로 3.2° 이상이 30 m 넘게, 구간 안에서만 봄)
    runs = []
    for a, e, x in sorted(longc, key=lambda t: t[0]):
        up = (x["long"] if forward else -x["long"]) >= LONG_FROM - EPS
        ov_a, ov_e = max(a, lo), min(e, hi)
        if not up or ov_e - ov_a < EPS:
            continue
        if runs and abs(runs[-1][1] - ov_a) < EPS:
            runs[-1][1] = ov_e
        else:
            runs.append([ov_a, ov_e])
    rests = [x["s"] for x in items.get("barriers", []) if x.get("type") == "rest" and x.get("flat") == "yes"
             and x.get("s") is not None]
    for a, e in runs:
        if e - a <= CLIMB_M + EPS:
            continue
        top = e if forward else a
        if any(a - EPS <= s <= e + EPS or abs(s - top) <= REST_NEAR_M + EPS for s in rests):
            continue
        add("climb_no_rest", 1)

    for a, e, g in _surface_spans(items):
        if g == "bad":
            add("surface_bad", _overlap(a, e, lo, hi))
        elif g == "very_bad":
            add("surface_very_bad", _overlap(a, e, lo, hi))

    for f in items.get("facilities") or []:
        if f.get("dest") != "main" or not _in_closed(f.get("s"), lo, hi):
            continue
        if f.get("type") == "curb_ramp":
            sl = [f.get("slope")]
        elif f.get("type") == "ramp":
            sl = [f.get(k) for k in ("slope_low", "slope_mid", "slope_top")]
        else:
            continue
        sl = [abs(x) for x in sl if x is not None]
        if sl:
            add("fac_slope", max(0.0, max(sl) - LONG_FROM))

    bars = items.get("barriers", [])
    has_passing = any(x.get("type") == "passing" for x in bars)
    rep = next((x.get("route_value") for x in bars if x.get("type") == "width_rep" and x.get("route_value") is not None), None)
    if rep is not None and rep < WIDE_CM and not has_passing:
        add("narrow_len", length)
    for x in bars:
        t, s = x.get("type"), x.get("s")
        if t == "bump":
            val = x.get("route_value")
            if val is not None and not x.get("unmeasured") and BUMP_LOW[0] - EPS <= val <= BUMP_LOW[1] + EPS \
                    and _in_closed(s, lo, hi):
                add("bump_low", 1)
        elif t == "narrow":
            val = x.get("route_value")
            if val is not None and val < min(WIDE_CM, rep if rep is not None else WIDE_CM) - EPS and _in_closed(s, lo, hi):
                add("narrow_point_long" if x.get("over5m") == "yes" else "narrow_point", 1)
        elif t == "driveway":
            c = x.get("cross")
            if c is None or abs(c) <= CROSS_FROM + EPS or not _in_closed(s, lo, hi):
                continue
            here = _value_at(crossc, s)
            if here is not None and abs(here["cross"]) > CROSS_FROM + EPS and w.get("cross", 0.0) > 0:
                continue  # 이 자리는 좌우 벌점을 이미 받음(좌우 계수가 있는 길만)
            add("driveway", 1)
        elif t == "hazard" and s is not None:
            e = x.get("s_end") if x.get("s_end") is not None else s
            ov = _overlap(s, e, lo, hi)
            if x.get("hazard") == "shared":
                add("shared", ov)
            elif x.get("hazard") == "drop":
                add("drop", ov)
                if x.get("guard") == "none" and x.get("leans") == "yes":
                    add("drop_open", ov)

    if j.state == "uncertain":
        add("uncertain", 1)
    bd = {k: round(x, 6) for k, x in bd.items()}
    return length + sum(bd.values()), bd


def make_cost_fn(w: dict):
    """route_engine.find_route의 cost_fn: (items, mode, lo, hi, forward, j) -> (비용, 벌점)."""
    def fn(items, mode, lo, hi, forward, j):
        return piece_cost(items, mode, lo, hi, forward, j, w)
    return fn
