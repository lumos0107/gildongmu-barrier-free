"""가중치 경로 Task 2: 비용 계산(route_cost.py)과 가중치 표. 설계 Docs/2026-11-21-가중치경로-설계.md 3장 나."""
import json
import math

import pytest

from route_cost import KEYS, effective, load_weights, piece_cost
from route_engine import Judgement
from test_route import b, seg, v

W1 = {k: 1.0 for k in KEYS}


def w(**kw):
    return {k: kw.get(k, 0.0) for k in KEYS}


def cost(it, lo, hi, forward=True, j=None, ww=None, mode="manual"):
    return piece_cost(it, mode, lo, hi, forward, j or Judgement(), ww if ww is not None else W1)


def test_fast_cost_is_length():
    ww = effective({"routes": {"fast": {}}, "mode_mult": {}}, "fast", "manual")
    assert ww == {k: 0.0 for k in KEYS}
    assert piece_cost(seg(values=[v(5.0, cross=4.0)]), "manual", 0.0, 20.0, True, Judgement(), ww) == (20.0, {})


def test_slope_piecewise():
    it = seg(values=[v(5.0, s=10.0), v(0.0, s=60.0)], L=100.0)
    c, bd = cost(it, 0.0, 100.0, ww=w(long=1.0))
    assert bd == {"long": pytest.approx(1.8 * 35)} and c == pytest.approx(100 + 63.0)


def test_bump_on_start_counted():
    it = seg(barriers=[b("bump", s=10.0, value=15)])
    assert cost(it, 0.0, 10.0, forward=False, ww=w(bump_low=15.0))[1] == {"bump_low": 15.0}


def test_bump_18_not_low():
    it = seg(barriers=[b("bump", s=10.0, value=18)])
    assert cost(it, 0.0, 20.0, ww=w(bump_low=15.0))[1] == {}


def test_climb_direction():
    it = seg(values=[v(4.0, s=20.0)], L=40.0)
    assert cost(it, 0.0, 40.0, True, ww=w(climb_no_rest=20.0))[1] == {"climb_no_rest": 20.0}
    assert cost(it, 0.0, 40.0, False, ww=w(climb_no_rest=20.0))[1] == {}


def test_climb_rest_cancels():
    it = seg(values=[v(4.0, s=20.0)], barriers=[{"type": "rest", "s": 40.0, "s_end": None, "flat": "yes"}], L=40.0)
    assert cost(it, 0.0, 40.0, True, ww=w(climb_no_rest=20.0))[1] == {}


def test_climb_rest_not_flat_counts():
    it = seg(values=[v(4.0, s=20.0)], barriers=[{"type": "rest", "s": 40.0, "s_end": None, "flat": "no"}], L=40.0)
    assert cost(it, 0.0, 40.0, True, ww=w(climb_no_rest=20.0))[1] == {"climb_no_rest": 20.0}


def test_climb_backward_negative():
    it = seg(values=[v(-4.0, s=20.0)], L=40.0)
    assert cost(it, 0.0, 40.0, False, ww=w(climb_no_rest=20.0))[1] == {"climb_no_rest": 20.0}
    assert cost(it, 0.0, 40.0, True, ww=w(climb_no_rest=20.0))[1] == {}
    it["barriers"].append({"type": "rest", "s": 0.0, "s_end": None, "flat": "yes"})
    assert cost(it, 0.0, 40.0, False, ww=w(climb_no_rest=20.0))[1] == {}


def test_climb_short_not_counted():
    it = seg(values=[v(4.0, s=10.0)], L=25.0)
    assert cost(it, 0.0, 25.0, True, ww=w(climb_no_rest=20.0))[1] == {}


def test_narrow_passing_cancels():
    rep = b("width_rep", s=None, value=120)
    assert cost(seg(barriers=[rep]), 0.0, 20.0, ww=w(narrow_len=0.5))[1] == {"narrow_len": 10.0}
    it = seg(barriers=[rep, {"type": "passing", "s": 5.0, "s_end": None}])
    assert cost(it, 0.0, 20.0, ww=w(narrow_len=0.5))[1] == {}


def test_narrow_point_vs_rep():
    rep = b("width_rep", s=None, value=120)
    it = seg(barriers=[rep, b("narrow", s=5.0, value=130), {"type": "passing", "s": 1.0, "s_end": None}])
    assert cost(it, 0.0, 20.0, ww=w(narrow_point=10.0))[1] == {}
    it = seg(barriers=[rep, b("narrow", s=5.0, value=100) | {"over5m": "yes"}, {"type": "passing", "s": 1.0, "s_end": None}])
    assert cost(it, 0.0, 20.0, ww=w(narrow_point=10.0, narrow_point_long=30.0))[1] == {"narrow_point_long": 30.0}


def test_drop_open_extra():
    it = seg(barriers=[{"type": "hazard", "hazard": "drop", "s": 0.0, "s_end": 10.0, "guard": "none", "leans": "yes"}])
    assert cost(it, 0.0, 20.0, ww=w(drop=1.0, drop_open=1.0))[1] == {"drop": 10.0, "drop_open": 10.0}
    it["barriers"][0]["guard"] = "rail"
    assert cost(it, 0.0, 20.0, ww=w(drop=1.0, drop_open=1.0))[1] == {"drop": 10.0}


def test_reversed_hazard_range():
    it = seg(barriers=[{"type": "hazard", "hazard": "shared", "s": 30.0, "s_end": 10.0}], L=40.0)
    assert cost(it, 0.0, 20.0, ww=w(shared=1.0))[1] == {"shared": 10.0}


def test_touching_range_zero():
    it = seg(barriers=[{"type": "hazard", "hazard": "shared", "s": 20.0, "s_end": 30.0}], L=40.0)
    assert cost(it, 0.0, 20.0, ww=w(shared=1.0))[1] == {}


def test_driveway_cross_once():
    dw = {"type": "driveway", "s": 10.0, "s_end": None, "cross": 4.0, "bump_mm": 0}
    it = seg(values=[v(0.0, s=10.0, cross=3.0)], barriers=[dw])
    assert cost(it, 0.0, 20.0, ww=w(cross=1.0, driveway=10.0))[1] == {"cross": pytest.approx(0.7 * 20)}
    it = seg(values=[v(0.0, s=10.0, cross=1.0)], barriers=[dw])
    assert cost(it, 0.0, 20.0, ww=w(cross=1.0, driveway=10.0))[1] == {"driveway": 10.0}


def test_cross_unknown_counts_points():
    it = seg(values=[v(0.0, s=5.0, cross=None), v(0.0, s=8.0, cross=None), v(0.0, s=30.0, cross=None)], L=40.0)
    assert cost(it, 0.0, 20.0, ww=w(cross_unknown=2.0))[1] == {"cross_unknown": 4.0}


def test_uncertain_piece():
    j = Judgement()
    j.worse("uncertain", "턱 20 mm")
    assert cost(seg(), 0.0, 20.0, j=j, ww=w(uncertain=30.0))[1] == {"uncertain": 30.0}
    assert j.state == "uncertain" and j.reasons == ["턱 20 mm"]  # 받은 판정을 바꾸지 않음


def test_surface_spans():
    it = seg(surfaces=[{"s": 0.0, "grade": "bad"}, {"s": 10.0, "grade": "good"}])
    assert cost(it, 0.0, 20.0, ww=w(surface_bad=0.5))[1] == {"surface_bad": 5.0}
    it = seg(surfaces=[{"s": 10.0, "grade": "very_bad"}, {"s": 20.0, "grade": "good"}])
    it["second"] = True  # 둘째 마디 출발: 앞 기록 s부터 자기 s까지(very_bad는 0~10)
    assert cost(it, 0.0, 20.0, ww=w(surface_very_bad=1.0))[1] == {"surface_very_bad": 10.0}


def test_fac_slope():
    it = seg()
    it["facilities"] = [{"type": "curb_ramp", "s": 10.0, "dest": "main", "slope": -8.0, "w_cm": 120, "end_mm": 0},
                        {"type": "ramp", "s": 12.0, "dest": "door", "slope_low": 9.0}]
    assert cost(it, 0.0, 20.0, ww=w(fac_slope=5.0))[1] == {"fac_slope": pytest.approx(4.8 * 5)}


def test_breakdown_sums():
    it = seg(values=[v(5.0, cross=4.0)], barriers=[b("bump", s=3.0, value=14)],
             surfaces=[{"s": 0.0, "grade": "bad"}])
    c, bd = cost(it, 2.0, 18.0)
    assert c == pytest.approx(16.0 + sum(bd.values())) and len(bd) >= 3


def test_zero_length_piece():
    it = seg(values=[v(5.0)], barriers=[b("bump", s=10.0, value=15)])
    assert cost(it, 10.0, 10.0) == (0.0, {})


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf")])
def test_bad_weights_raise(tmp_path, bad):
    f = tmp_path / "w.json"
    f.write_text(json.dumps({"version": "x", "routes": {"fast": {}, "comfort": {"long": bad}, "safe": {}}, "mode_mult": {}}),
                 encoding="utf-8")
    with pytest.raises(ValueError):
        load_weights(f)
    good = {"routes": {"comfort": {"long": 1.0}}, "mode_mult": {}}
    with pytest.raises(ValueError):
        effective(good, "comfort", "manual", personal={"long": bad})


def test_unknown_key_raises(tmp_path):
    f = tmp_path / "w.json"
    f.write_text(json.dumps({"version": "x", "routes": {"comfort": {"slopee": 1.0}}, "mode_mult": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_weights(f)
    with pytest.raises(ValueError):
        effective({"routes": {"comfort": {}}, "mode_mult": {}}, "comfort", "manual", personal={"slopee": 2.0})


def test_real_weights_file_loads():
    import pathlib
    wt = load_weights(pathlib.Path(__file__).resolve().parents[1] / "route_weights.json")
    assert set(wt["routes"]) == {"fast", "comfort", "safe"} and wt["routes"]["fast"] == {}
    assert all(k in wt["why"] for r in wt["routes"].values() for k in r)
    e = effective(wt, "comfort", "manual")
    assert e["long"] == 1.5 and e["shared"] == 0.0 and all(math.isfinite(x) and x >= 0 for x in e.values())


def test_driveway_safe_only_weight():
    """최종 검토: 안전한 길(좌우 계수 0)에서는 좌우가 가파른 진출입부도 벌점을 받아야 함."""
    dw = {"type": "driveway", "s": 10.0, "s_end": None, "cross": 4.0, "bump_mm": 0}
    it = seg(values=[v(0.0, s=10.0, cross=3.0)], barriers=[dw])
    assert cost(it, 0.0, 20.0, ww=w(driveway=10.0))[1] == {"driveway": 10.0}
