"""거리뷰 판정 반영(jejunu/apply_roadview.py) 시험 — 2026-11-21 팀 결정 A.
거리뷰로 본 연석 넘는 곳의 가상 턱 높이는 '높이 모름(확인 필요)'으로, 엉뚱한 자리의 가상 연석경사로는 뺀다."""
import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "jejunu"))

import apply_roadview as AR  # noqa: E402
from route_engine import judge  # noqa: E402


def bump(seg, s, value=14):
    return {"type": "bump", "value": value, "seg": seg, "s": s, "s_end": None, "route_value": value,
            "uncertain_for": [], "unmeasured": False, "flags": []}


def ramp(seg, s, slope=6.9):
    return {"type": "curb_ramp", "name": "가상 연석경사로", "w_cm": 110, "slope": slope, "end_mm": 0, "dest": "main",
            "seg": seg, "s": s, "flags": [], "uncertain_for": []}


def rin(barriers, facilities=()):
    return {"format": "bf-route-input-1", "site": "jejunu1000", "barriers": list(barriers), "facilities": list(facilities)}


def point(no, shape, items, conf="높음", lip="연석 높이 그대로"):
    return {"no": no, "shape": shape, "lip": lip, "confidence": conf,
            "items": [{"kind": k, "seg": g, "s": s} for k, g, s in items]}


def test_checked_bump_becomes_unknown():
    new, ch = AR.apply(rin([bump(7, 3.0, 14)]), [point(9, "일반 연석(턱 있음)", [("턱", 7, 3.0)])])
    b = new["barriers"][0]
    assert b["route_value"] is None and b["value"] is None and b["unmeasured"] is True
    assert b["virtual"] == {"value": 14, "route_value": 14}
    assert b["roadview"] == {"no": 9, "shape": "일반 연석(턱 있음)", "lip": "연석 높이 그대로", "confidence": "높음"}
    assert len(ch["bumps"]) == 1


def test_unchecked_bump_untouched():
    other = bump(8, 1.0, 20)
    new, _ = AR.apply(rin([other]), [point(9, "일반 연석(턱 있음)", [("턱", 7, 3.0)])])
    assert new["barriers"][0] == other


def test_s_tolerance():
    pts = [point(1, "모름", [("턱", 7, 3.005)])]
    new, _ = AR.apply(rin([bump(7, 3.0), bump(7, 3.5)]), pts)
    assert new["barriers"][0]["unmeasured"] is True
    assert new["barriers"][1]["unmeasured"] is False


def test_misplaced_curb_ramp_removed():
    pts = [point(1, "일반 연석(턱 있음)", [("연석경사로", 407, 10.2), ("턱", 407, 10.2)])]
    new, ch = AR.apply(rin([bump(407, 10.2)], [ramp(407, 10.2), ramp(500, 1.0)]), pts)
    assert [(f["seg"], f["s"]) for f in new["facilities"]] == [(500, 1.0)]
    assert [(f["seg"], f["s"]) for f in ch["removed_curb_ramps"]] == [(407, 10.2)]


def test_curb_ramp_kept_when_roadview_says_ramp_or_unknown():
    pts = [point(1, "연석경사로", [("연석경사로", 1, 1.0)]), point(2, "모름", [("연석경사로", 2, 1.0)])]
    new, ch = AR.apply(rin([], [ramp(1, 1.0), ramp(2, 1.0)]), pts)
    assert len(new["facilities"]) == 2 and ch["removed_curb_ramps"] == []


def test_original_not_modified():
    src = rin([bump(7, 3.0)], [ramp(7, 3.0)])
    keep = copy.deepcopy(src)
    AR.apply(src, [point(1, "일반 연석(턱 있음)", [("연석경사로", 7, 3.0), ("턱", 7, 3.0)])])
    assert src == keep


def test_unmatched_items_reported():
    _, ch = AR.apply(rin([bump(7, 3.0)]), [point(1, "모름", [("턱", 9, 1.0)])])
    assert ch["missing"] == [{"no": 1, "kind": "턱", "seg": 9, "s": 1.0}]


def test_header_summary():
    pts = [point(1, "일반 연석(턱 있음)", [("연석경사로", 7, 3.0), ("턱", 7, 3.0)])]
    new, _ = AR.apply(rin([bump(7, 3.0)], [ramp(7, 3.0)]), pts)
    assert new["roadview"]["bumps_unknown"] == 1 and new["roadview"]["curb_ramps_removed"] == 1
    assert new["format"] == "bf-route-input-1"


def test_judge_says_height_unknown():
    new, _ = AR.apply(rin([bump(7, 3.0, 25)]), [point(1, "일반 연석(턱 있음)", [("턱", 7, 3.0)])])
    items = {"seg": 7, "len": 10.0, "status": "done", "missing": [], "values": [], "surfaces": [],
             "barriers": new["barriers"]}
    j = judge(items, "manual")
    assert j.state == "uncertain" and "턱 높이 모름" in j.reasons and not any("25 mm" in r for r in j.reasons)


def test_real_files():
    D = ROOT / "jejunu/out"
    src = json.loads(AR.SRC.read_text(encoding="utf-8"))  # 거리뷰 반영 전 판(2026-11-22부터 백업 폴더)
    pts = json.loads((D / "거리뷰/판정_합본.json").read_text(encoding="utf-8"))
    new, ch = AR.apply(src, pts)
    assert len(ch["bumps"]) == 135 and len(ch["removed_curb_ramps"]) == 5 and ch["missing"] == []
    assert sum(1 for f in new["facilities"] if f["type"] == "curb_ramp") == 3
    assert sum(1 for b in new["barriers"] if b["type"] == "bump") == 278


def test_real_files_with_second_round():
    """1차 89곳(판정_합본) + 2차 6곳(판정_2차, 반영 뒤 새 길이 새로 지나게 된 턱 7개)."""
    src = json.loads(AR.SRC.read_text(encoding="utf-8"))
    pts = AR.load_points()
    assert len(pts) == 95
    _, ch = AR.apply(src, pts)
    assert len(ch["bumps"]) == 142 and len(ch["removed_curb_ramps"]) == 5 and ch["missing"] == []


# ── 반영 효과(jejunu/roadview_effect.py): 새 길이 거리뷰로 안 본 가상 턱 · 남은 가상 연석경사로를 지나는지 ──
import roadview_effect as RE  # noqa: E402


def _route(*steps):
    return {"steps": [{"seg": g, "s0": a, "s1": b} for g, a, b in steps]}


def test_unchecked_on_routes():
    checked = bump(1, 2.0) | {"unmeasured": True}
    src = rin([checked, bump(1, 5.0, 12), bump(2, 9.0, 30)], [ramp(1, 6.0), ramp(3, 1.0)])
    got = RE.unchecked_on(src, [_route((1, 0.0, 8.0)), _route((1, 8.0, 0.0))])
    assert got == [{"kind": "턱", "seg": 1, "s": 5.0, "virtual": 12},
                   {"kind": "연석경사로", "seg": 1, "s": 6.0, "virtual": 6.9}]
