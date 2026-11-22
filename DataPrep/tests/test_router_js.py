"""앱 안 자바스크립트 길찾기(router.js)가 엔진과 같은지(B단계 Task 3). node가 없으면 건너뛴다.
같음 기준(계획 Global Constraints): 상태 · 지나는 조각(구간, s0, s1, 방향 순서) · 판정 · 이유 · length_m · cost · compare · same_as가 글자까지 같다."""
import json
import pathlib
import shutil
import subprocess
import time

import pytest

import route_cost as RC
import route_engine as R
import route_export as RX
import three_compare as TC

# 공개 저장소 사본에서는 저장소의 app/에 있는 router.js를, 원본(Unity 프로젝트)에서는 앱 껍데기 폴더의 것을 시험한다(11/22)
_REPO_APP = pathlib.Path(__file__).resolve().parents[2] / "app"
MAKE = _REPO_APP if (_REPO_APP / "router.js").exists() else \
    pathlib.Path(r"C:\Users\seungjun\Documents\work\베리어프리\캡스톤2\14_앱껍데기\_만들기")
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None or not (MAKE / "router_cli.js").exists(), reason="node 또는 router.js 없음")
WT = RC.load_weights(RX.HERE / "route_weights.json")
LV = [{}] + [{g: lv} for g in RX.GROUPS for lv in ("less", "more")] + [
    {"slope": "more", "floor": "less", "road": "more"}, {"slope": "less", "floor": "more", "road": "less"},
    {"slope": "more", "floor": "more", "road": "more"}, {"slope": "less", "floor": "less", "road": "less"}]


def run_js(tmp_path, G, queries):
    gp, qp, op = tmp_path / "g.json", tmp_path / "q.json", tmp_path / "o.json"
    gp.write_text(json.dumps(G, ensure_ascii=False), encoding="utf-8")
    qp.write_text(json.dumps(queries, ensure_ascii=False), encoding="utf-8")
    t0 = time.time()
    subprocess.run([NODE, str(MAKE / "router_cli.js"), str(gp), str(qp), str(op)], check=True)
    return json.loads(op.read_text(encoding="utf-8")), time.time() - t0


def sub(r):
    return {"status": r["status"], "length_m": r["length_m"], "uncertain_segs": r["uncertain_segs"], "cost": r["cost"],
            "compare": r["compare"], "same_as": r["same_as"], "blocked_by": r["blocked_by"],
            "steps": [[x["seg"], x["s0"], x["s1"], x["state"], x["reasons"]] for x in r["steps"]]}


def norm(x):
    return json.loads(json.dumps(x, ensure_ascii=False))


@pytest.mark.parametrize("site", ["minsokchon", "jejunu1000"])
def test_router_matches_engine(site, tmp_path):
    ctx, facs, start = TC.load_site(site)
    G = RX.export_graph(ctx, facs, start, WT)
    names = list(G["goals"])
    every = 1 if site == "minsokchon" else 4  # 제주대 조합은 도착 4곳에 1곳(엔진 시간), 기본값은 모든 도착
    qs = [{"goal": n, "mode": m, "levels": lv} for lv_i, lv in enumerate(LV) for i, n in enumerate(names)
          for m in R.MODES if lv_i == 0 or i % every == 0]
    got, sec = run_js(tmp_path, G, qs)
    print(f"{site}: node {len(qs)}질의 {sec:.1f}초")
    bad = []
    for q, g in zip(qs, got):
        want = R.three_routes(ctx, tuple(G["start"]), tuple(G["goals"][q["goal"]]), q["mode"], WT, RX.personal_of(q["levels"]))
        for rk in R.ROUTE_KEYS:
            if norm(sub(g[rk])) != norm(sub(want[rk])):
                bad.append((q, rk))
    assert bad == [], bad[:3]


def test_personal_of_same_as_python(tmp_path):
    G = {"format": RX.FORMAT, "segs": [], "start": [0, 0.0], "goals": {}, "pieces": [], "weights": WT, "keys": list(RC.KEYS),
         "groups": {g: list(k) for g, k in RX.GROUPS.items()}, "levels": RX.LEVELS}
    got, _ = run_js(tmp_path, G, [{"personalOf": lv} for lv in LV])
    assert got == [RX.personal_of(lv) for lv in LV]


def test_py_round(tmp_path):
    cases = [[2.675, 2], [0.125, 2], [4.35, 1], [2.5, 0], [3.5, 0], [-0.5, 0], [0.0005, 3], [1.0005, 3],
             [123.4565, 3], [7.45, 1], [0.15, 1], [1e-7, 6], [5e-7, 6], [1.5e-6, 6], [99.95, 1]]
    import random
    rng = random.Random(3)
    cases += [[round(rng.uniform(0, 1000), rng.choice([3, 4, 5, 7])), rng.choice([0, 1, 3, 6])] for _ in range(3000)]
    got, _ = run_js(tmp_path, {"format": RX.FORMAT}, [{"pyRound": c} for c in cases])
    want = [round(x, n) for x, n in cases]
    assert [g == w for g, w in zip(got, want)] == [True] * len(cases), [(c, g, w) for c, g, w in zip(cases, got, want) if g != w][:5]


# ── 작은 반례 자료 ───────────────────────────────────────────────────────────────
def _items(L, values=(), barriers=(), status="done"):
    return {"len": L, "status": status, "missing": [], "values": list(values), "barriers": list(barriers),
            "surfaces": [], "facilities": []}


def _v(s, long=0.0, cross=0.0):
    return {"s": s, "long": long, "cross": cross, "uncertain_for": []}


def _ctx(segs):
    """segs: {k: (a, b, items)}"""
    return R.Ctx(segs={k: {"a": a, "b": b, "len": it["len"]} for k, (a, b, it) in segs.items()},
                 items={k: it for k, (_, _, it) in segs.items()}, test=True, site="t", facility_rules=True)


def _cases():
    flat = lambda L: _items(L, [_v(s) for s in range(0, int(L) + 1, 5)])  # noqa: E731
    climb = _items(60.0, [_v(s, long=4.0) for s in range(0, 61, 5)])
    bump = _items(20.0, [_v(0), _v(20)], [{"type": "bump", "s": 10.0, "s_end": None, "route_value": 15, "uncertain_for": [],
                                              "unmeasured": False}])
    dw = _items(20.0, [_v(10.0, cross=3.0)], [{"type": "driveway", "s": 10.0, "cross": 4.0, "bump_mm": 15}])
    steps = lambda L: _items(L, [_v(0)], [{"type": "steps", "s": 1.0, "s_end": None}])  # noqa: E731
    twin = 10.0 + 5e-13
    cw = json.loads(json.dumps(WT))
    cw["routes"]["safe"]["cross"] = 1.0  # 진출입부 두 갈래를 모두 쓰게(좌우·진출입부 계수 둘 다)
    return {
        "마디 위 출발·같은 구간": (_ctx({1: (100, 101, flat(30.0)), 2: (101, 102, flat(20.0))}),
                            (1, 0.0), {"g1": [1, 20.0], "g2": [2, 20.0]}, WT),
        "같은 구간 다른 s": (_ctx({1: (100, 101, flat(30.0))}), (1, 5.0), {"g": [1, 25.0]}, WT),
        "경계 점 양쪽": (_ctx({1: (100, 101, flat(10.0)), 2: (101, 102, bump), 3: (102, 103, flat(10.0))}),
                    (2, 10.0), {"a": [1, 0.0], "b": [3, 10.0]}, WT),
        "진출입부 두 갈래": (_ctx({1: (100, 101, dw)}), (1, 0.0), {"g": [1, 20.0]}, cw),
        "동점과 1e-12": (_ctx({1: (100, 101, flat(10.0)), 2: (100, 101, flat(10.0)), 3: (100, 101, _items(twin, [_v(0)])),
                           4: (99, 100, flat(5.0)), 5: (101, 102, flat(5.0))}), (4, 0.0), {"g": [5, 5.0]}, WT),
        "1e-11 더 싼 쪽": (_ctx({1: (100, 101, flat(10.0)), 2: (100, 101, flat(10.0)), 3: (100, 101, _items(10.0 - 2e-11, [_v(0)])),
                               4: (99, 100, flat(5.0)), 5: (101, 102, flat(5.0))}), (4, 0.0), {"g": [5, 5.0]}, WT),
        "막힌 수 우선": (_ctx({1: (100, 101, steps(50.0)), 2: (100, 102, steps(5.0)), 3: (102, 101, steps(5.0)),
                          4: (99, 100, flat(5.0)), 5: (101, 103, flat(5.0))}), (4, 0.0), {"g": [5, 5.0]}, WT),
        "연결 없음": (_ctx({1: (100, 101, flat(10.0)), 2: (200, 201, flat(10.0))}), (1, 0.0), {"g": [2, 5.0]}, WT),
        "역방향 오르막": (_ctx({1: (100, 101, climb)}), (1, 60.0), {"down": [1, 0.0]}, WT),
    }


@pytest.mark.parametrize("name", list(_cases()))
def test_router_edge_cases(name, tmp_path):
    ctx, start, goals, w = _cases()[name]
    G = RX.graph_from_points(ctx, start, goals, w)
    qs = [{"goal": g, "mode": m, "levels": lv} for g in goals for m in R.MODES for lv in (LV[0], LV[7], LV[8])]
    got, _ = run_js(tmp_path, G, qs)
    for q, g in zip(qs, got):
        want = R.three_routes(ctx, tuple(start), tuple(goals[q["goal"]]), q["mode"], w, RX.personal_of(q["levels"]))
        for rk in R.ROUTE_KEYS:
            assert norm(sub(g[rk])) == norm(sub(want[rk])), (name, q, rk)
