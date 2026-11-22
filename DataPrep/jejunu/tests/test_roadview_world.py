"""거리뷰 결과를 설계도에 반영(설계 Docs/2026-11-22-거리뷰반영-3D맵-설계.md) 시험."""
import json
import pathlib

import pytest

import build_world as BW
import obstacles as OB

BACKUP = pathlib.Path(__file__).resolve().parents[3] / "Docs/backup_20261122/거리뷰반영전/virtual_world.json"
CURB = "일반 연석(턱 있음)"


def _pt(no, shape, items, conf="중간"):
    return {"no": no, "shape": shape, "lip": "모름", "confidence": conf,
            "items": [{"kind": k, "seg": g, "s": s} for k, g, s in items]}


# ── 규칙 ────────────────────────────────────────────────────────────────────
def test_load_and_match_roadview():
    rv = BW.load_roadview_points([_pt(3, CURB, [("턱", 7, 3.0), ("연석경사로", 7, 3.0)])])
    assert BW.roadview_at(rv, "턱", 7, 3.04)["shape"] == CURB
    assert BW.roadview_at(rv, "턱", 7, 3.05 + 1e-9)["no"] == 3  # 경로입력은 0.1 m 반올림이라 0.05 m 차이도 같은 턱
    assert BW.roadview_at(rv, "턱", 7, 3.1) is None
    assert BW.roadview_at(rv, "턱", 8, 3.0) is None
    assert BW.roadview_at(rv, "연석경사로", 7, 3.0)["no"] == 3


def test_drop_misplaced_curb_ramps_only():
    rv = BW.load_roadview_points([_pt(1, CURB, [("연석경사로", 7, 3.0)]), _pt(2, "모름", [("연석경사로", 8, 1.0)]),
                                  _pt(3, "연석경사로", [("연석경사로", 9, 1.0)])])
    facs = [{"type": "curb_ramp", "seg": 7, "s": 3.0}, {"type": "curb_ramp", "seg": 8, "s": 1.0},
            {"type": "curb_ramp", "seg": 9, "s": 1.0}, {"type": "bench", "seg": 7, "s": 3.0}]
    kept, removed = BW.drop_roadview_ramps(facs, rv)
    assert [(f["type"], f["seg"]) for f in kept] == [("curb_ramp", 8), ("curb_ramp", 9), ("bench", 7)]
    assert [(f["seg"], f["s"]) for f in removed] == [(7, 3.0)]


def test_driveway_bump_copies_height_unless_unread():
    assert OB.driveway_bump([{"s": 5.0, "mm": 15}], 6.0) == (15, None)
    assert OB.driveway_bump([{"s": 5.0, "mm": 130, "unread": True}], 6.0) == (None, ["bump_mm"])
    assert OB.driveway_bump([{"s": 1.0, "mm": 15}], 6.0) == (0, None)


# ── 다시 만든 설계도(out/virtual_world.json) ─────────────────────────────────
def _bumps(w):
    return {(s["id"], b["s"]): b for s in w["segs"] for b in s["bumps"]}


def test_world_marks_roadview_bumps(world):
    rvb = [b for s in world["segs"] for b in s["bumps"] if b.get("unread")]
    assert len(rvb) == 142
    assert all(b["unread"] is True and set(b["roadview"]) == {"no", "shape", "lip", "confidence"} for b in rvb)


def test_world_same_as_before_except_roadview(world):
    if not BACKUP.exists():
        pytest.skip("이전 판 없음")
    old = json.loads(BACKUP.read_text(encoding="utf-8"))
    ob, nb = _bumps(old), _bumps(world)
    assert set(ob) == set(nb)  # 턱 자리 그대로
    for k, b in nb.items():  # 높이·모양·출처 그대로, 거리뷰로 본 턱에 unread · roadview만 더함
        assert {x: v for x, v in b.items() if x not in ("unread", "roadview")} == ob[k]
    for so, sn in zip(old["segs"], world["segs"]):
        assert {x: v for x, v in so.items() if x != "bumps"} == {x: v for x, v in sn.items() if x != "bumps"}
    assert world["terrain"] == old["terrain"]
    gone = [f for f in old["facilities"] if f not in world["facilities"]]
    assert len(gone) == 5 and all(f["type"] == "curb_ramp" for f in gone)
    assert [f for f in old["facilities"] if f not in gone] == world["facilities"]
    assert len(world["obstacles"]) == len(old["obstacles"])
    n_dw = 0
    for o, n in zip(old["obstacles"], world["obstacles"]):
        if n != o:  # 바뀐 것은 '높이 모름' 턱 옆 진출입부 턱 높이뿐
            assert n["type"] == "driveway" and n["bump_mm"] is None and n["unread"] == ["bump_mm"]
            assert {k: v for k, v in n.items() if k not in ("bump_mm", "unread")} == {k: v for k, v in o.items() if k != "bump_mm"}
            n_dw += 1
    assert n_dw > 0


# ── 다시 만든 경로입력(out/경로입력_가상.json): 앱의 '못 잼'과 같은 결과 ─────────────
def test_route_input_has_unread_bumps(world):
    ri = json.loads((BW.OUT / "경로입력_가상.json").read_text(encoding="utf-8"))
    un = [b for b in ri["barriers"] if b["type"] == "bump" and b["unmeasured"]]
    assert len(un) == 142 and all(b["route_value"] is None for b in un)
    segs = {s["seg"]: s for s in ri["segments"]}
    assert all("barrier_value" in segs[b["seg"]]["missing"] for b in un)  # 앱 규칙: 못 잰 장벽이 있으면 구간을 다 재지 못함
    assert sum(1 for f in ri["facilities"] if f["type"] == "curb_ramp") == 3
    dw = [b for b in ri["barriers"] if b["type"] == "driveway" and b.get("bump_mm") is None]
    assert dw and all(b["unmeasured"] for b in dw)
