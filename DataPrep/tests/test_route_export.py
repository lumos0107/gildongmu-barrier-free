"""길 그래프 내보내기·파이썬 기준 구현(B단계 Task 2) 시험. 계획 Docs/2026-11-22-B단계-작업계획.md"""
import pytest

import route_cost as RC
import route_engine as R
import route_export as RX
import three_compare as TC

WT = RC.load_weights(RX.HERE / "route_weights.json")
L, N, M = 0.5, 1.0, 2.0
COMBOS = [None] + [RX.personal_of({g: lv}) for g in RX.GROUPS for lv in ("less", "more")] + [
    RX.personal_of({"slope": "more", "floor": "less", "road": "more"}),
    RX.personal_of({"slope": "less", "floor": "more", "road": "less"}),
    RX.personal_of({"slope": "more", "floor": "more", "road": "more"}),
    RX.personal_of({"slope": "less", "floor": "less", "road": "less"})]


@pytest.fixture(scope="module", params=["minsokchon", "jejunu1000"])
def site(request):
    ctx, facs, start = TC.load_site(request.param)
    return ctx, facs, start, RX.export_graph(ctx, facs, start, WT)


def test_personal_of_groups():
    p = RX.personal_of({"slope": "more", "road": "less"})
    assert p["long"] == 2.0 and p["climb_no_rest"] == 2.0 and p["shared"] == 0.5 and p["driveway"] == 0.5
    assert "uncertain" not in p and "cross_unknown" not in p and p.get("surface_bad", 1.0) == 1.0


def test_piece_cost_terms_param_changes_nothing(site):
    ctx, _, _, G = site
    w = RC.effective(WT, "comfort", "manual")
    for k, s0, s1, *_ in G["pieces"][:200]:
        j = R.Judgement(state="uncertain")
        assert RC.piece_cost(ctx.items[k], "manual", s0, s1, True, j, w) == \
            RC.piece_cost(ctx.items[k], "manual", s0, s1, True, j, w, terms=[])


def test_terms_rebuild_piece_cost_exactly(site):
    ctx, _, _, G = site
    for k, s0, s1, judg, tf, tb, tf0, tb0 in G["pieces"]:
        for mode in R.MODES:
            state = judg[mode][0]
            for rk in R.ROUTE_KEYS:
                for pp in COMBOS:
                    w = RC.effective(WT, rk, mode, pp)
                    for fwd, t, t0 in ((True, tf, tf0), (False, tb, tb0)):
                        want = RC.piece_cost(ctx.items[k], mode, s0, s1, fwd, R.Judgement(state=state), w)
                        assert RX.cost_from(RX.pick_terms(t, t0, w), state, s1 - s0, w) == want


def _sub(r):
    return {"status": r["status"], "length_m": r["length_m"], "uncertain_segs": r["uncertain_segs"],
            "cost": r["cost"], "compare": r["compare"], "same_as": r["same_as"], "blocked_by": r["blocked_by"],
            "steps": [(x["seg"], x["s0"], x["s1"], x["state"], x["reasons"]) for x in r["steps"]]}


def test_ref_matches_engine(site):
    ctx, facs, start, G = site
    for pp in (None, COMBOS[7], COMBOS[8]):
        for name, (k, s) in G["goals"].items():
            for mode in R.MODES:
                want = R.three_routes(ctx, tuple(G["start"]), (k, s), mode, WT, pp)
                got = RX.ref_three(G, name, mode, WT, pp)
                for rk in R.ROUTE_KEYS:
                    assert _sub(got[rk]) == _sub(want[rk]), (name, mode, rk, pp)


def _seg(values=(), barriers=(), L=60.0):
    return {"seg": 1, "len": L, "status": "done", "missing": [], "values": list(values), "barriers": list(barriers),
            "surfaces": [], "facilities": []}


def test_climb_direction_differs():
    items = _seg([{"s": s, "long": 4.0, "cross": 0.0, "uncertain_for": []} for s in range(0, 61, 5)])
    tf, tb = RX.piece_terms(items, 0.0, 60.0, True, {"cross": 1.0}), RX.piece_terms(items, 0.0, 60.0, False, {"cross": 1.0})
    assert ("climb_no_rest", 1) in tf and ("climb_no_rest", 1) not in tb


def test_driveway_variant():
    items = _seg([{"s": 10.0, "long": 0.0, "cross": 3.0, "uncertain_for": []}],
                 [{"type": "driveway", "s": 10.0, "cross": 4.0, "bump_mm": 15}], L=20.0)
    with_cross = RX.piece_terms(items, 0.0, 20.0, True, {"cross": 1.0})
    no_cross = RX.piece_terms(items, 0.0, 20.0, True, {"cross": 0.0})
    assert ("driveway", 1) not in with_cross and ("driveway", 1) in no_cross


def test_unstable_s_flags_positions_rounding_would_change(site):
    """앱은 3자리로 반올림한 s로 조각 그림 선을 찾는다. 반올림해서 바뀌는 s가 있으면 build_shell이 멈춰야 한다(B 미룬 것, 11/22)."""
    _, _, _, G = site
    assert RX.unstable_s(G) == []
    bad = {"pieces": [[1, 0.0, 10.0005, {}, [], [], None, None], [2, 0.25, 3.0, {}, [], [], None, None]]}
    assert RX.unstable_s(bad) == [(1, 0.0, 10.0005)]
