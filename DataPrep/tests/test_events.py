import pytest

from conftest import in_steps, long_at
from virtual_events import test_pack as make_test_pack


def test_test_pack(pack):
    t = make_test_pack(pack)
    assert t["test"] is True and t["hash"] != "c5ad2ca2ed6f" and pack["test"] is False and t["net"] == "19e1a1e4665f"


def test_events_shape(events, pack_t):
    assert all(e["test"] is True and e["site"] == "minsokchon" and e["net"] == "19e1a1e4665f" and e["pack"] == pack_t["hash"] for e in events)


def test_route_input(ri, world):
    assert ri["format"] == "bf-route-input-1" and ri["test"] is True
    assert len(ri["segments"]) == 307 and all(s["status"] == "done" for s in ri["segments"])
    assert 950 <= len(ri["values"]) <= 1200


def test_values_match_world(ri, world):
    """경로입력 앞뒤 값은 설계도 값을 앱처럼 0.1°로 반올림한 것이라 0.05° 안에서 같다."""
    for v in ri["values"]:
        if not in_steps(world, v["seg"], v["s"]):
            assert abs(v["long"] - long_at(world, v["seg"], v["s"])) <= 0.05 + 1e-9


def test_uncertain_present(ri):
    assert any("uncertain" in v["flags"] for v in ri["values"])
    assert any(b["uncertain_for"] for b in ri["barriers"] if b["type"] == "bump")


def test_no_out_of_seg(ri):
    assert not any("out_of_seg" in x["flags"] for x in ri["values"] + ri["barriers"])


def test_real_pack_rejects(evening, events, pack):
    with pytest.raises(ValueError):
        evening.route_input(events, pack, allow_test=True)


def test_cross_missing_like_app(ri, plan):
    """앱처럼 좌우를 묻지 않는 지점(계획 cross: false)은 경로입력의 좌우 값이 비어 있다."""
    n_skip = sum(1 for v in plan.values() for p in v if not p.get("cross", True))
    assert n_skip > 0
    assert sum(1 for v in ri["values"] if v["cross"] is None) == n_skip
    assert all(s["status"] == "done" for s in ri["segments"])


def test_events_like_app(events, ri):
    """앱과 같은 모양: 표시값 0.1 m, 경사·좌우 0.1°, 짧은 구간에 더한 지점은 more,
    앞뒤 재확인 범위(4.5~5.0°, 5.5~5.9°)와 좌우 재확인 범위(2.0~2.5°)는 값 두 개."""
    rules = {"long": [[4.5, 5.0], [5.5, 5.9]], "cross": [[2.0, 2.5]]}
    inr = lambda v, rr: any(a - 1e-9 <= abs(v) <= b + 1e-9 for a, b in rr)
    for e in events:
        d = e["data"]
        if "mark" in d and d["mark"] is not None:
            assert abs(d["mark"] * 10 - round(d["mark"] * 10)) < 1e-6, d
        if e["kind"] == "slope":
            assert all(abs(v * 10 - round(v * 10)) < 1e-6 for v in d["values"] + d["cross"]), d
            if inr(d["values"][0], rules["long"]):
                assert len(d["values"]) == 2, d
            if d["cross"] and inr(d["cross"][0], rules["cross"]):
                assert len(d["cross"]) == 2, d
    assert all(s["status"] == "done" for s in ri["segments"])


def test_short_segment_point_is_more(events, plan):
    runs = {e["id"]: e["data"]["seg"] for e in events if e["kind"] == "run_start"}
    empty = {sid for sid, p in plan.items() if not p}
    kinds = [e["data"]["kind"] for e in events if e["kind"] == "slope" and runs[e["run"]] in empty]
    assert kinds and all(k == "more" for k in kinds)


def test_barriers_match_world(ri, world):
    """경로입력의 턱·계단·노면이 설계도와 같다(위치는 표시값 0.1 m 반올림만큼, 0.05 m 안)."""
    tol = 0.05 + 1e-6
    by = {s["id"]: s for s in world["segs"]}
    near = lambda a, b: abs(a - b) <= tol
    bumps = [b for b in ri["barriers"] if b["type"] == "bump"]
    assert len(bumps) == sum(len(s["bumps"]) for s in world["segs"])
    for b in bumps:
        assert any(near(x["s"], b["s"]) and x["mm"] == b["value"] and x["dir"] == b["dir"] for x in by[b["seg"]]["bumps"]), b
    steps = [b for b in ri["barriers"] if b["type"] == "steps"]
    assert len(steps) == sum(len(s["steps"]) for s in world["segs"])
    for b in steps:
        assert any((near(x["s0"], b["s"]) or near(x["s1"], b["s"])) and x["count"] == b["count"] for x in by[b["seg"]]["steps"]), b
    assert len(ri["surfaces"]) == sum(len(s["surf"]) for s in world["segs"])
    for x in ri["surfaces"]:
        assert any((near(y["s0"], x["s"]) or near(y["s1"], x["s"])) and y["material"] == x["material"] and y["grade"] == x["grade"]
                   for y in by[x["seg"]]["surf"]), x


# ── 거리뷰 반영(2026-11-22): 거리뷰로 본 턱은 앱의 '못 잼'처럼 적는다 ──
from virtual_events import bump_event  # noqa: E402


def test_bump_event_like_before():
    b = {"s": 3.0, "mm": 15, "dir": "up", "shape": "smooth", "run_mm": 120}
    assert bump_event(b, 3.0, False) == {"type": "bump", "mark": 3.0, "value": 15, "dir": "up", "shape": "smooth",
                                         "repeat": "no", "run_mm": 120}
    sq = bump_event({**b, "shape": "square", "run_mm": 0}, 2.0, True)
    assert sq["dir"] == "down" and "run_mm" not in sq and "unread" not in sq


def test_unread_bump_event_like_app():
    d = bump_event({"s": 3.0, "mm": 130, "dir": "up", "shape": "square", "run_mm": 0, "unread": True}, 3.0, False)
    assert d["value"] is None and d["unread"] == ["value"] and d["shape"] == "square"
