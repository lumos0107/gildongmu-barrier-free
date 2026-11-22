"""2·3차 항목(가상): 장애물 16종과 시설 7종이 가상 경로입력에 모두 나오고 앱 칸과 맞는다."""
import math

import numpy as np

BARRIERS = {"bump", "gap", "width_rep", "narrow", "steps", "broken", "dead_end", "nogo", "hazard", "temp_block",
            "rest", "passing", "turn", "driveway", "puddle", "other"}
FACILITIES = {"toilet", "entrance", "ramp", "curb_ramp", "parking", "bench", "service"}


def test_all_barrier_types(ri):
    assert BARRIERS <= {b["type"] for b in ri["barriers"]}


def test_all_facility_types(ri):
    assert FACILITIES <= {f["type"] for f in ri["facilities"]}
    assert all(f["seg"] is not None and f["s"] is not None for f in ri["facilities"])


def test_route_still_done(ri):
    assert all(s["status"] == "done" for s in ri["segments"])
    assert not any("out_of_seg" in b["flags"] for b in ri["barriers"])


def test_easyjeju_main_entrance(world):
    fac = world["facilities"]
    ent = [f for f in fac if f["type"] == "entrance" and "이지제주" in f["src"]]
    ramp = [f for f in fac if f["type"] == "ramp" and "이지제주" in f["src"]]
    assert ent and ent[0]["sill_mm"] == 100
    assert ramp and all(abs(ramp[0][k] - 5.0) < 1e-9 for k in ("slope_low", "slope_mid", "slope_top"))


def test_osm_nogo_entrances(world):
    ents = [f for f in world["facilities"] if f["type"] == "entrance" and f["src"].startswith("OSM wheelchair=no")]
    assert len(ents) >= 3 and all(f["sill_mm"] >= 120 for f in ents)


def test_app_ranges(world):
    for o in world["obstacles"]:
        if o["type"] == "narrow":
            assert 30 <= o["value"] < 150
        if o["type"] == "gap":
            assert 8 <= o["value"] <= 60 and o["dir"] in ("parallel", "cross")
        if o["type"] == "hazard":
            assert o["hazard"] in ("ends_road", "ends_steps", "ends_drop", "drop", "shared")
    for f in world["facilities"]:
        if "door_cm" in f:
            assert 60 <= f["door_cm"] <= 120
        if "sill_mm" in f:
            assert 0 <= f["sill_mm"] <= 300
        assert f["src"]


def test_drop_terrain(world, inp):
    """길 옆 낙차가 있는 곳은 그쪽 땅이 길보다 0.5 m 넘게 낮다."""
    from virtual_world import Terrain, point_at, seg_profile, height_at
    t = world["terrain"]
    ter = Terrain(n=t["n"], cell=t["cell"], origin=t["origin"], h=np.array(t["h"]).reshape(t["n"], t["n"]))
    by = {s["id"]: s for s in inp.segs}
    ws = {s["id"]: s for s in world["segs"]}
    drops = [o for o in world["obstacles"] if o["type"] == "hazard" and o["hazard"] == "drop"]
    assert len(drops) >= 3
    for o in drops:
        s = (o["s"] + o["s_end"]) / 2
        p, d = point_at(by[o["seg"]], s)
        left = np.array([-d[1], d[0]]) * (1 if o["drop_side"] == "left" else -1)
        q = p + left * (by[o["seg"]]["w"] / 2 + 2.5)
        assert ter.height(*q) < height_at(seg_profile(ws[o["seg"]]), s) - 0.5


def test_osm_toilet_wheelchair(world):
    """OSM에 장애인 화장실 표시(toilets:wheelchair)가 있는 화장실은 무작위 대신 그 값을 쓰고 출처를 적는다."""
    wc = [f for f in world["facilities"] if f["type"] == "toilet"]
    osm = [f for f in wc if "toilets:wheelchair=" in f["src"]]
    assert osm, [f["src"] for f in wc]
    assert all(f["stall"] == ("yes" if "toilets:wheelchair=yes" in f["src"] else "no") for f in osm)


def test_toilet_on_real_building(world, inp):
    """시설 목록에서 건물 안에 찍힌 화장실(실제 건물이 있음)은 on_building이 참이라 3D에서 가상 상자를 따로 세우지 않는다."""
    import json
    pois = json.loads((inp.site_dir / "시설목록.geojson").read_text(encoding="utf-8"))["features"]
    inside = {p["properties"]["name"] for p in pois
              if p["properties"]["type"] == "화장실" and (p["properties"].get("building") or {}).get("dist_m") == 0}
    assert inside
    wc = {f["name"]: f for f in world["facilities"] if f["type"] == "toilet"}
    assert all(wc[n]["on_building"] for n in inside if n in wc)
    assert not any(f["on_building"] for n, f in wc.items() if n not in inside)


def _osm_m(inp, f):
    import json
    from virtual_obstacles import _ll_to_m
    meta = json.loads((inp.site_dir / "aerial_z19.json").read_text(encoding="utf-8"))
    g = f["geometry"]
    ring = g["coordinates"][0] if g["type"] == "Polygon" else [g["coordinates"]]
    ring = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    return _ll_to_m(meta, sum(c[0] for c in ring) / len(ring), sum(c[1] for c in ring) / len(ring))


def test_parking_at_osm_disabled_space(world, inp):
    """장애인 주차는 OSM 장애인 주차 칸(parking_space=disabled) 자리에 두고 출처에 OSM을 적는다."""
    osm = [f for f in inp.osm["features"] if f["properties"].get("parking_space") == "disabled"]
    assert osm
    pk = [f for f in world["facilities"] if f["type"] == "parking"]
    assert len(pk) == 1 and "OSM" in pk[0]["src"]
    assert min(math.hypot(pk[0]["x"] - ox, pk[0]["z"] - oz) for ox, oz in (_osm_m(inp, f) for f in osm)) <= 5


def test_toilet_src_says_where(world, inp):
    """화장실 출처 칸은 자리 근거를 시설 목록과 같게 적는다(OSM 건물이면 'OSM', 추정이면 '안내도')."""
    import json
    pois = {p["properties"]["name"]: p["properties"] for p in
            json.loads((inp.site_dir / "시설목록.geojson").read_text(encoding="utf-8"))["features"]}
    for f in world["facilities"]:
        if f["type"] == "toilet":
            want = "자리는 OSM" if pois[f["name"]]["how"].startswith("OSM") else "자리는 공식 안내도"
            assert want in f["src"], (f["name"], f["src"])


def test_no_facility_in_steps(world):
    """시설(목적지)은 계단 안에 놓이지 않는다(계단 0.3 m 밖)."""
    by = {s["id"]: s for s in world["segs"]}
    for f in world["facilities"]:
        for st in by[f["seg"]]["steps"]:
            assert not (st["s0"] - 0.3 < f["s"] < st["s1"] + 0.3), (f["type"], f.get("name"), f["seg"], f["s"], st)
