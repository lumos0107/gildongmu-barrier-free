"""가중치 경로 Task 3: 방향 있는 가중치 길 찾기(find_route의 cost_fn). 그래프는 test_route.make_ctx와 같음.
   1 ─10─ 2 ─11─ 3      (10 m씩)
   1 ─12─ 4 ─13─ 3      (15 m씩)
"""
import pytest

from route_cost import KEYS, make_cost_fn
from route_engine import Ctx, find_route
from test_route import b, make_ctx, seg, v


def fn(**kw):
    return make_cost_fn({k: kw.get(k, 0.0) for k in KEYS})


def used(r):
    return [x["seg"] for x in r["steps"] if x["s0"] != x["s1"]]


def test_cost_fn_none_unchanged():
    r = find_route(make_ctx(), (10, 0.0), (11, 10.0), "manual")
    assert "cost" not in r and "breakdown" not in r and used(r) == [10, 11]


def test_fast_is_shortest():
    r = find_route(make_ctx(), (10, 0.0), (11, 10.0), "manual", cost_fn=fn())
    assert used(r) == [10, 11] and r["cost"] == pytest.approx(20.0) and r["breakdown"] == {}


def test_comfort_avoids_slope():
    ctx = make_ctx({10: {"values": [v(4.0, s=5.0)]}, 11: {"values": [v(4.0, s=5.0)]}})
    assert used(find_route(ctx, (10, 0.0), (11, 10.0), "manual", cost_fn=fn())) == [10, 11]
    r = find_route(ctx, (10, 0.0), (11, 10.0), "manual", cost_fn=fn(long=1.0))
    assert used(r) == [12, 13] and r["status"] == "ok" and r["cost"] == pytest.approx(30.0)


def test_stage_beats_penalty():
    ctx = make_ctx({10: {"values": [v(4.0, s=5.0)]}, 11: {"values": [v(4.0, s=5.0)]},
                    12: {"barriers": [b("bump", s=5.0, value=20)]}})
    r = find_route(ctx, (10, 0.0), (11, 10.0), "manual", cost_fn=fn(long=100.0))
    assert r["status"] == "ok" and used(r) == [10, 11]


def line_ctx(**kw):
    """1 ─30─ 2 (40 m) 하나. a→b가 오르막(+4.0°)."""
    it = seg(values=[v(4.0, s=20.0)], L=40.0, **kw) | {"seg": 30}
    return Ctx(segs={30: {"a": 1, "b": 2, "len": 40.0}}, items={30: it}, test=True, site="test")


def test_direction_costs_differ():
    up = find_route(line_ctx(), (30, 0.0), (30, 40.0), "manual", cost_fn=fn(climb_no_rest=20.0))
    down = find_route(line_ctx(), (30, 40.0), (30, 0.0), "manual", cost_fn=fn(climb_no_rest=20.0))
    assert up["breakdown"] == {"climb_no_rest": 20.0} and down["breakdown"] == {}
    assert up["cost"] == pytest.approx(60.0) and down["cost"] == pytest.approx(40.0)


def test_stage3_lexicographic():
    ctx = make_ctx({10: {"barriers": [b("steps", s=5.0)]}, 11: {"barriers": [b("steps", s=5.0)]},
                    12: {"barriers": [b("steps", s=5.0)]}, 13: {"values": [v(4.0, s=5.0)]}})
    r = find_route(ctx, (10, 0.0), (11, 10.0), "manual", cost_fn=fn(long=1e6))
    assert r["status"] == "none" and used(r) == [12, 13] and [x["seg"] for x in r["blocked_by"]] == [12]


def test_node_start_bump_once():
    ctx = make_ctx({10: {"barriers": [b("bump", s=0.0, value=15)]}})
    r = find_route(ctx, (10, 0.0), (11, 10.0), "manual", cost_fn=fn(bump_low=5.0))  # 20+5 < 우회 30
    assert used(r) == [10, 11] and r["breakdown"] == {"bump_low": 5.0}


def test_same_segment_partial():
    ctx = make_ctx({12: {"barriers": [b("bump", s=1.0, value=15), b("bump", s=6.0, value=15)]}})
    r = find_route(ctx, (12, 2.0), (12, 10.0), "manual", cost_fn=fn(bump_low=15.0))
    assert used(r) == [12] and r["breakdown"] == {"bump_low": 15.0} and r["cost"] == pytest.approx(23.0)


def test_cost_equals_length_plus_breakdown():
    ctx = make_ctx({10: {"values": [v(5.0, s=5.0, cross=4.0)], "surfaces": [{"s": 0.0, "grade": "bad"}]},
                    13: {"barriers": [b("bump", s=3.0, value=14)]}})
    for mode in ("manual", "power", "stroller"):
        r = find_route(ctx, (10, 2.0), (13, 9.0), mode, cost_fn=fn(**{k: 1.0 for k in KEYS}))
        assert r["cost"] == pytest.approx(r["length_m"] + sum(r["breakdown"].values()), abs=1e-3)
        assert r["cost"] == pytest.approx(sum(x["cost"] for x in r["steps"]), abs=1e-3)
