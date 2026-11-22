def test_fields_and_seg(fl, pack, world):
    segs = {s["seg"] for s in pack["segs"]}
    by = {s["id"]: s for s in world["segs"]}
    for f in fl["features"]:
        p = f["properties"]
        assert {"no", "name", "type", "how", "est_error_m", "aerial_px", "building", "seg", "seg_dist_m", "src"} <= set(p)
        assert p["seg"] in segs and not by[p["seg"]]["steps"]


def test_aerial_px_matches_pack_space(fl, pack):
    W, H = pack["map"]["W"], pack["map"]["H"]
    assert all(0 <= f["properties"]["aerial_px"][0] < W and 0 <= f["properties"]["aerial_px"][1] < H for f in fl["features"])


def test_names_unique(fl):
    names = [f["properties"]["name"] for f in fl["features"]]
    assert len(names) == len(set(names))


def test_has_buildings_and_bus_stops(fl):
    types = [f["properties"]["type"] for f in fl["features"]]
    assert types.count("building") >= 50 and types.count("bus_stop") >= 3


def _stepfree_reach(pack, world):
    steps = {s["id"] for s in world["segs"] if s["steps"]}
    adj = {}
    for s in pack["segs"]:
        if s["seg"] in steps:
            continue
        adj.setdefault(s["a"], []).append((s["b"], s["seg"]))
        adj.setdefault(s["b"], []).append((s["a"], s["seg"]))
    seen, segs, st = {pack["start_node"]}, set(), [pack["start_node"]]
    while st:
        u = st.pop()
        for v, sid in adj.get(u, []):
            segs.add(sid)
            if v not in seen:
                seen.add(v)
                st.append(v)
    return segs


def test_facilities_reachable_without_stairs(fl, pack, world):
    ok = _stepfree_reach(pack, world)
    bad = [f["properties"]["name"] for f in fl["features"] if f["properties"]["seg"] not in ok]
    assert not bad, bad[:10]


def test_building_facility_close_to_its_seg(fl):
    far = [(f["properties"]["name"], f["properties"]["seg_dist_m"]) for f in fl["features"] if f["properties"]["type"] == "building" and f["properties"]["seg_dist_m"] > 3.0]
    assert not far, far[:10]


def test_main_gate_is_gate_on_path(fl):
    """'제주대학교정문'은 건물이 아니라 길 위 출입 지점(gate), 자리 근거는 1:1,000 문주(팀 결정 2026-11-15)."""
    g = [f["properties"] for f in fl["features"] if f["properties"]["name"] == "제주대학교정문"]
    assert len(g) == 1
    p = g[0]
    assert p["type"] == "gate" and p["building"] is None
    assert p["src"].startswith("1:1000(") and "문주" in p["src"]
    assert p["seg_dist_m"] <= 0.5
