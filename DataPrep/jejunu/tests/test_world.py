import json
import math

import virtual_world as vw
from build_world import KERB_RULES
from common import OUT
from conftest import MINSOKCHON_WORLD


def test_same_keys_as_minsokchon(world):
    ms = json.loads(MINSOKCHON_WORLD.read_text(encoding="utf-8"))
    assert set(ms["segs"][0]) <= set(world["segs"][0])
    assert {"terrain", "segs", "obstacles", "facilities", "walls"} <= set(world)


def test_slope_is_terrain_not_random(world, ter_raw, mp):
    by = {s["id"]: s for s in mp["segs"]}
    sel = [s for s in world["segs"] if by[s["id"]]["kind"] == "sidewalk" and s["len"] > 30 and not s["steps"] and not s["bumps"]][:20]
    assert len(sel) == 20
    for s in sel:
        m = s["len"] / 2
        p0, p1 = vw.point_at(by[s["id"]], m - 5)[0], vw.point_at(by[s["id"]], m + 5)[0]
        raw = math.degrees(math.atan((ter_raw.height(*p1) - ter_raw.height(*p0)) / 10))
        pr = vw.seg_profile(s)
        got = math.degrees(math.atan((vw.height_at(pr, m + 5) - vw.height_at(pr, m - 5)) / 10))
        assert abs(raw - got) < 0.5


def test_kerbs_from_map(world, mp):
    want = sum(len(s["kerbs"]) for s in mp["segs"] if not vw.is_loop(s))
    got = sum(1 for s in world["segs"] for b in s["bumps"] if b["src"].startswith("가상(턱 높이"))
    assert got >= 0.9 * want


def test_kerbs_follow_rules(world):
    for kind, bands in KERB_RULES.items():
        got = [b for s in world["segs"] for b in s["bumps"] if b["src"] == f"가상(턱 높이, {kind})"]
        assert got and all(any(lo <= b["mm"] <= hi and b["shape"] in sh for _, lo, hi, sh in bands) for b in got)
    plain = [b for s in world["segs"] for b in s["bumps"] if b["src"] == "가상(턱 높이, plain)"]
    assert 0.3 <= sum(b["mm"] >= 100 for b in plain) / len(plain) <= 0.5


def test_no_bump_on_loop_or_corner_or_steps(world, mp):
    by = {s["id"]: s for s in mp["segs"]}  # 꺾임은 선 좌표가 있는 맵 자료 구간으로 잰다
    for s in world["segs"]:
        if vw.is_loop(s):
            assert not s["bumps"]
        for b in s["bumps"]:
            assert not vw.in_steps(s, b["s"])  # 꺾임 옆은 허용(턱 자리는 지도 자리, VirtualCheck가 '참고'로 따로 셈)


def test_every_item_has_src(world):
    for s in world["segs"]:
        for k in ("cross", "bumps", "steps", "surf"):
            assert all("src" in x for x in s[k])


def test_stair_report_written():
    assert (OUT / "계단_높이대조.csv").exists()


def test_stair_count_follows_terrain():
    import numpy as np
    from build_world import stair_counts

    class Inp:  # 길이 7 m 계단(길이로 세면 20단), 땅 높이 차 0.9 m → 6단
        segs = [{"id": 1, "a": 0, "b": 1, "len": 7.0, "p": [0, 0, 7, 0]}]
        steps = [{"p": [0, 0, 7, 0]}]
    ter = vw.Terrain(n=11, cell=1.0, origin=-1.0, h=np.tile(np.linspace(0, 1.3, 11), (11, 1)))
    st = stair_counts(Inp(), ter)
    assert st[1][0][2] == 6


def test_no_bump_near_any_slope_point(world, pack):
    """턱을 넣은 뒤의 실제 경사로 '더 재는 지점'을 다시 셈해도, 모든 경사 지점이 턱에서 (반폭 + 0.6 m) 넘게 떨어진다."""
    E = vw._evening()
    inp = vw.Inputs(segs=world["segs"], pack=pack, net={}, osm={}, size_m=0.0)
    plan = vw.plan_points(inp)
    rules = pack["rules"]
    pseg = {s["seg"]: s for s in pack["segs"]}
    bad = []
    for s in world["segs"]:
        if not s["bumps"]:
            continue
        pts = plan.get(s["id"]) or [{"mark": round(s["len"] / 2, 1), "kind": "more", "both": False, "cross": True}]
        sgn = -1 if vw.is_loop(s) else 1
        longs = [round(sgn * vw.long_at(s, vw.to_world(s, p["mark"])), 1) for p in pts]
        more = vw.more_points(E, pseg[s["id"]], pts, longs, rules)
        xs = [vw.to_world(s, p["mark"]) for p in pts + more]
        for b in s["bumps"]:
            half = b["run_mm"] / 2000
            if any(abs(x - b["s"]) <= half + 0.6 for x in xs):
                bad.append((s["id"], b["s"]))
    assert not bad, bad[:10]


def test_width_within_app_range(world, pack):
    mx = pack["rules"]["width"]["max_cm"]
    assert all(0 < s["width_cm"] <= mx for s in world["segs"])
    assert any(s["w"] * 100 > mx for s in world["segs"])  # 3D 폭은 실제 폭 그대로

