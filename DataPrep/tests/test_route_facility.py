"""가중치 경로 Task 1: 시설 판정(경사로 · 연석경사로 · 진출입부)과 안내만 하는 항목. 설계 Docs/2026-11-21-가중치경로-설계.md 6장 1)."""
import pytest

from route_engine import judge
from test_route import b, seg


def fac(t, s=10.0, dest="main", **kw):
    return {"type": t, "s": s, "dest": dest, **kw}


def with_fac(*facs, barriers=()):
    it = seg(barriers=barriers)
    it["facilities"] = list(facs)
    return it


@pytest.mark.parametrize("slope,mode,want", [(4.4, "manual", "ok"), (4.8, "manual", "uncertain"), (5.1, "manual", "blocked"),
                                             (5.6, "power", "uncertain"), (6.0, "power", "blocked"), (9.0, "stroller", "ok")])
def test_curb_ramp_slope(slope, mode, want):
    it = with_fac(fac("curb_ramp", slope=slope, w_cm=120, end_mm=0))
    assert judge(it, mode, facility_rules=True).state == want


def test_ramp_uses_max_of_three():
    it = with_fac(fac("ramp", slope_low=4.3, slope_mid=5.1, slope_top=4.0, w_cm=150))
    j = judge(it, "manual", facility_rules=True)
    assert j.state == "blocked" and "경사로 5.1°" in j.reasons


def test_ramp_negative_slope():
    it = with_fac(fac("ramp", slope_low=-5.2, slope_mid=-1.0, slope_top=-1.0, w_cm=150))
    j = judge(it, "manual", facility_rules=True)
    assert j.state == "blocked" and "경사로 5.2°" in j.reasons


def test_ramp_slope_missing_note_only():
    it = with_fac(fac("ramp", slope_low=None, slope_mid=None, slope_top=None, w_cm=150))
    j = judge(it, "manual", facility_rules=True)
    assert j.state == "ok" and "경사로 기울기 기록 없음" in j.notes


@pytest.mark.parametrize("mm,want", [(23, "blocked"), (20, "uncertain"), (10, "ok")])
def test_curb_ramp_end_bump(mm, want):
    j = judge(with_fac(fac("curb_ramp", slope=3.0, w_cm=120, end_mm=mm)), "power", facility_rules=True)
    assert j.state == want
    if want != "ok":
        assert f"연석경사로 끝 턱 {mm} mm" in j.reasons


@pytest.mark.parametrize("cm,want", [(79, "blocked"), (85, "uncertain"), (90, "ok")])
def test_facility_width(cm, want):
    j = judge(with_fac(fac("curb_ramp", slope=3.0, w_cm=cm, end_mm=0)), "power", facility_rules=True)
    assert j.state == want


def test_door_facility_ignored():
    j = judge(with_fac(fac("curb_ramp", dest="door", slope=8.0, w_cm=60, end_mm=40)), "manual", facility_rules=True)
    assert j.state == "ok" and j.reasons == []


def test_driveway_bump():
    it = seg(barriers=[{"type": "driveway", "s": 10.0, "s_end": None, "cross": 2.0, "bump_mm": 35}])
    j = judge(it, "stroller", facility_rules=True)
    assert j.state == "blocked" and "진출입부 턱 35 mm" in j.reasons


def test_driveway_bump_dedup():
    it = seg(barriers=[{"type": "driveway", "s": 10.0, "s_end": None, "cross": 2.0, "bump_mm": 35},
                       b("bump", s=10.5, value=21)])
    j = judge(it, "manual", facility_rules=True)
    assert j.state == "blocked"
    assert [r for r in j.reasons if "턱" in r] == ["진출입부 턱 35 mm"]


def test_driveway_bump_same_value():
    it = seg(barriers=[{"type": "driveway", "s": 10.0, "s_end": None, "cross": 2.0, "bump_mm": 15},
                       b("bump", s=10.0, value=15)])
    j = judge(it, "manual", facility_rules=True)
    assert j.state == "ok" and j.reasons == []


def test_puddle_turn_notes():
    it = seg(barriers=[{"type": "puddle", "s": 3.0, "s_end": None}, {"type": "turn", "s": 4.0, "s_end": None}])
    j = judge(it, "manual", facility_rules=True)
    assert j.state == "ok" and "물 고임(안내만)" in j.notes and "회전 공간 기록(안내만)" in j.notes


def test_facility_outside_range():
    j = judge(with_fac(fac("curb_ramp", s=15.0, slope=9.0, w_cm=120, end_mm=0)), "manual", lo=0.0, hi=10.0,
              facility_rules=True)
    assert j.state == "ok"


CASES = [
    with_fac(fac("curb_ramp", slope=9.0, w_cm=60, end_mm=40)),
    with_fac(fac("ramp", slope_low=-6.0, slope_mid=None, slope_top=None, w_cm=70)),
    seg(barriers=[{"type": "driveway", "s": 10.0, "s_end": None, "cross": 5.0, "bump_mm": 35},
                  {"type": "puddle", "s": 3.0, "s_end": None}, {"type": "turn", "s": 4.0, "s_end": None}]),
]


@pytest.mark.parametrize("i", range(len(CASES)))
@pytest.mark.parametrize("mode", ["manual", "power", "stroller"])
def test_facility_rules_off_unchanged(i, mode):
    it = CASES[i]
    plain = {k: v for k, v in it.items() if k != "facilities"}
    off, ref = judge(it, mode), judge(plain, mode)
    assert (off.state, off.reasons, off.notes, off.cost) == (ref.state, ref.reasons, ref.notes, ref.cost)
    assert off.state == "ok" and off.notes == []


def test_driveway_dedup_only_in_range():
    """최종 검토: 같은 자리 턱이 조각 밖이면 진출입부 턱 판정을 빼지 않음."""
    it = seg(barriers=[{"type": "driveway", "s": 10.0, "s_end": None, "cross": 2.0, "bump_mm": 35},
                       b("bump", s=10.8, value=40)])
    j = judge(it, "manual", lo=0.0, hi=10.4, facility_rules=True)
    assert j.state == "blocked" and "진출입부 턱 35 mm" in j.reasons
