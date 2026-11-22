import json

from conftest import marks_values
from virtual_world import build_world, to_world

MATERIALS = ["asphalt", "concrete", "block", "slab", "stone", "gravel", "songi", "soil", "grass", "deck", "rubber", "coir", "other"]
GRADES = ["good", "intermediate", "bad", "very_bad"]


def test_steps_segments(world):
    st = {s["id"]: s["steps"] for s in world["segs"] if s["steps"]}
    assert set(st) == {190, 65, 202}
    s190 = next(s for s in world["segs"] if s["id"] == 190)
    assert st[190][0]["s0"] <= 0.01 and st[190][0]["s1"] >= s190["len"] - 0.01
    assert all(x["src"] == "OSM" and 0.14 <= x["rise_m"] / x["count"] <= 0.18 for v in st.values() for x in v)


def test_materials_and_grades(world):
    spans = [x for s in world["segs"] for x in s["surf"]]
    assert all(sum(x["material"] == m for x in spans) >= 2 for m in MATERIALS)
    assert all(sum(x["grade"] == g for x in spans) >= 2 for g in GRADES)
    assert all(x["reason"] for x in spans if x["grade"] == "very_bad")


def test_surface_coverage(world):
    for s in world["segs"]:
        sp = sorted(s["surf"], key=lambda x: x["s0"])
        assert abs(sp[0]["s0"]) < 1e-6 and abs(sp[-1]["s1"] - s["len"]) < 1e-6
        assert all(abs(a["s1"] - b["s0"]) < 1e-6 for a, b in zip(sp, sp[1:]))


def test_osm_surface_and_gravel(world, osm_surface_segs, gravel_nogo_segs):
    assert len(osm_surface_segs) >= 50 and gravel_nogo_segs
    by = {s["id"]: s for s in world["segs"]}
    for sid, mat in osm_surface_segs.items():
        assert all(x["material"] == mat and x["src"] == "OSM" for x in by[sid]["surf"])
    for sid in gravel_nogo_segs:
        assert any(x["material"] == "gravel" and x["grade"] == "very_bad" and x["src"] == "OSM" for x in by[sid]["surf"])


def test_boundary_cases(world, plan):
    longs, crosses = marks_values(world, plan)
    bumps = [b["mm"] for s in world["segs"] for b in s["bumps"]]
    assert sum(4.5 <= abs(v) <= 5.0 for v in longs) >= 5 and sum(5.5 <= abs(v) <= 5.9 for v in longs) >= 5
    assert sum(2.0 <= v <= 2.5 for v in crosses) >= 5
    assert sum(12 <= v <= 14 for v in bumps) >= 3 and sum(18 <= v <= 22 for v in bumps) >= 5


def test_realistic_bump_mix():
    """11/15 팀 결정(제주대와 같은 '현실형 섞기'): 경계 사례 밖 턱은 60%가 낮은 턱 13~17 mm(기록 시작 13 mm, 통과),
    40%가 높은 턱 30~60 mm(막힘). 같은 씨앗이면 같은 값."""
    from virtual_world import realistic_bumps
    v = realistic_bumps(38, 7)
    n_low = round(0.6 * 38)
    assert len(v) == 38
    assert sum(13 <= x <= 17 for x in v) == n_low and sum(30 <= x <= 60 for x in v) == 38 - n_low
    assert realistic_bumps(38, 7) == v


def test_world_bump_mix(world):
    """설계도의 턱: 23~29 mm나 60 mm 넘는 턱이 없고(경계 사례 18~22 mm만 불확실), 22 mm 넘어 막는 턱은 절반 미만."""
    mm = [b["mm"] for s in world["segs"] for b in s["bumps"]]
    assert not [x for x in mm if 23 <= x <= 29 or x > 60]
    assert sum(x > 22 for x in mm) < 0.5 * len(mm)


def test_value_ranges(world, plan):
    longs, crosses = marks_values(world, plan)
    assert all(abs(v) < 15 for v in longs) and all(0 <= v < 10 for v in crosses)
    assert all(0 < b["mm"] <= 300 for s in world["segs"] for b in s["bumps"])


def test_no_bump_near_marks(world, plan):
    for s in world["segs"]:
        for b in s["bumps"]:
            lo, hi = b["s"] - b["run_mm"] / 2000, b["s"] + b["run_mm"] / 2000
            assert all(to_world(s, p["mark"]) < lo - 0.6 or to_world(s, p["mark"]) > hi + 0.6 for p in plan[s["id"]])
            assert 1.0 <= b["s"] <= s["len"] - 1.0


def test_features_avoid_steps(world):
    for s in world["segs"]:
        for st in s["steps"]:
            assert all(b["s"] < st["s0"] - 0.5 or b["s"] > st["s1"] + 0.5 for b in s["bumps"])
            assert all(c["s1"] <= st["s0"] or c["s0"] >= st["s1"] for c in s["cross"])


def test_width(world):
    assert all(s["width_cm"] == round(s["w"] * 100) for s in world["segs"])


def test_world_reproducible(inp):
    a, b = build_world(inp, 7), build_world(inp, 7)
    a.pop("built")
    b.pop("built")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_no_trench(world, inp):
    """길 양옆 6 m 땅이 길 높이와 크게 다르지 않다(도랑·벽이 없다). 계단 구간은 뺀다."""
    import numpy as np
    from virtual_world import Terrain, point_at, seg_profile, height_at
    t = world["terrain"]
    ter = Terrain(n=t["n"], cell=t["cell"], origin=t["origin"], h=np.array(t["h"]).reshape(t["n"], t["n"]))
    by = {s["id"]: s for s in inp.segs}
    diffs = []
    for s in world["segs"]:
        if s["steps"]:
            continue
        pr = seg_profile(s)
        for x in np.arange(2.5, s["len"], 5.0):
            p, d = point_at(by[s["id"]], x)
            left = np.array([-d[1], d[0]])
            h = height_at(pr, x)
            for side in (1, -1):
                q = p + left * side * (s["w"] / 2 + 6)
                diffs.append(abs(ter.height(*q) - h))
    diffs = np.array(diffs)
    assert (diffs <= 1.5).mean() >= 0.95 and diffs.max() <= 4.0


def test_bump_height_on_slope(world):
    """경사진 곳의 턱도, 턱 앞뒤 경사선 사이 높이 차가 설계도 mm와 같다(VirtualCheck와 같은 재는 법)."""
    from virtual_world import height_at, seg_profile
    for s in world["segs"]:
        pr = seg_profile(s)
        for b in s["bumps"]:
            half = b["run_mm"] / 2000
            a, c = b["s"] - half - 0.02, b["s"] + half + 0.02
            ha, hc, h0 = height_at(pr, a), height_at(pr, c), height_at(pr, a - 0.3)
            mm = (hc - ha - (ha - h0) / 0.3 * (c - a)) * 1000
            want = (1 if b["dir"] == "up" else -1) * b["mm"]
            assert abs(mm - want) <= 1.0, (s["id"], b, mm)


def test_features_avoid_sharp_corners(world, inp):
    """30° 넘게 꺾이는 선 꼭짓점 근처에는 턱(1.5 m)과 좌우 기울기 토막(1.2 m)을 두지 않는다(3D 띠가 접히는 곳)."""
    from virtual_world import sharp_corners
    by = {s["id"]: s for s in inp.segs}
    for s in world["segs"]:
        for v in sharp_corners(by[s["id"]]):
            assert all(abs(b["s"] - v) >= 1.5 for b in s["bumps"]), (s["id"], v)
            assert all(c["s1"] <= v - 1.2 or c["s0"] >= v + 1.2 for c in s["cross"]), (s["id"], v)


def test_cross_edges_away_from_marks(world, plan):
    """좌우 기울기 토막의 시작·끝(구간 끝이 아닌 곳)은 측정 지점에서 1.6 m 넘게 떨어진다(3D 띠가 비틀리는 곳을 피함)."""
    for s in world["segs"]:
        ms = [to_world(s, p["mark"]) for p in plan[s["id"]]]
        for c in s["cross"]:
            for e in (c["s0"], c["s1"]):
                if e > 1e-6 and abs(e - s["len"]) > 1e-6:
                    assert all(abs(e - m) >= 1.6 for m in ms), (s["id"], c, ms)


def test_no_terrain_over_path(world, inp):
    """길 표면(좌우 기울기 포함) 위로 땅이 올라오지 않는다(길이 땅에 묻히지 않음)."""
    import math
    import numpy as np
    from virtual_world import Terrain, point_at, seg_profile, height_at, cross_deg
    t = world["terrain"]
    ter = Terrain(n=t["n"], cell=t["cell"], origin=t["origin"], h=np.array(t["h"]).reshape(t["n"], t["n"]))
    by = {s["id"]: s for s in inp.segs}
    worst = 0.0
    for s in world["segs"]:
        pr = seg_profile(s)
        for x in np.arange(0.13, s["len"], 0.37):
            p, d = point_at(by[s["id"]], x)
            left = np.array([-d[1], d[0]])
            h = height_at(pr, x)
            c = next((c for c in s["cross"] if c["s0"] <= x <= c["s1"]), None)
            tan = math.tan(math.radians(c["deg"])) if c else 0.0
            sgn = -1 if c and c["low"] == "left" else 1
            for o in np.linspace(-s["w"] / 2, s["w"] / 2, 5):
                surf = h + sgn * o * tan
                worst = max(worst, ter.height(*(p + left * o)) - surf)
    assert worst <= 1e-6, worst


def test_check_world(world, plan):
    """설계도 조건 검사: 정상 설계도는 문제가 없고, 20° 구간을 만들면 잡는다."""
    import copy
    from virtual_world import check_world
    assert check_world(world, plan) == []
    bad = copy.deepcopy(world)
    s = next(x for x in bad["segs"] if not x["steps"] and x["len"] > 20)
    pr = s["prof"]
    for i in range(0, len(pr), 2):
        pr[i + 1] = pr[i] * 0.364  # 약 20°
    assert any("앞뒤" in p for p in check_world(bad, plan))


def test_stairs_rise_matches_profile(world):
    """계단의 적힌 높이(rise_m)는 높이 단면의 실제 높이 차와 같고, 한 칸 높이는 0.14~0.18 m다."""
    from virtual_world import height_at, seg_profile
    for s in world["segs"]:
        pr = seg_profile(s)
        for st in s["steps"]:
            real = abs(height_at(pr, st["s1"]) - height_at(pr, st["s0"]))
            assert abs(st["rise_m"] - real) < 0.005, (s["id"], st, real)
            assert 0.14 <= st["rise_m"] / st["count"] <= 0.18


def test_no_bump_near_any_slope_point(world, events):
    """'더 재는 지점'과 짧은 구간 가운데 지점까지, 가상 기록의 모든 경사 지점은 턱 앞뒤 0.6 m 밖에 있다."""
    runs = {e["id"]: e["data"]["seg"] for e in events if e["kind"] == "run_start"}
    by = {s["id"]: s for s in world["segs"]}
    n = 0
    for e in events:
        if e["kind"] != "slope":
            continue
        s = by[runs[e["run"]]]
        x = to_world(s, e["data"]["mark"])
        n += 1
        for b in s["bumps"]:
            lo, hi = b["s"] - b["run_mm"] / 2000, b["s"] + b["run_mm"] / 2000
            assert x < lo - 0.6 or x > hi + 0.6, (s["id"], e["data"]["mark"], b)
    assert n > 1000
