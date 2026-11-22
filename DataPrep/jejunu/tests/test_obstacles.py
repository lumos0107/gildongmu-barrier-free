import virtual_world as vw


def test_drop_from_walls(obs):
    d = [o for o in obs["obstacles"] if o.get("hazard") == "drop"]
    assert d and all(o["src"].startswith("1:1000") for o in d)


def test_shared_only_on_walkable_roads(obs, mp):
    roads = {s["id"] for s in mp["segs"] if s["kind"].startswith("road")}
    assert {o["seg"] for o in obs["obstacles"] if o.get("hazard") == "shared"} <= roads


def test_entrances_steps_and_stepfree(obs):
    kinds = {f["src"].startswith("가상") for f in obs["facilities"] if f["type"] == "entrance"}
    assert kinds == {True, False}


def test_no_items_on_loops_or_steps(obs, world):
    by = {s["id"]: s for s in world["segs"]}
    for o in obs["obstacles"] + obs["facilities"]:
        s = by[o["seg"]]
        assert not vw.is_loop(s)
        if o.get("type") != "hazard":
            assert not vw.in_steps(s, o["s"])


def test_all_types_present(obs):
    t_obs = {o["type"] for o in obs["obstacles"]}
    t_fac = {f["type"] for f in obs["facilities"]}
    assert {"narrow", "gap", "nogo", "broken", "other", "hazard", "temp_block", "puddle", "rest", "passing", "turn", "dead_end", "driveway"} <= t_obs
    assert {"entrance", "toilet", "parking", "ramp", "curb_ramp", "bench", "service"} <= t_fac


def test_drops_measured_before_pressing(obs):
    """낙차 깊이는 길 아래 땅을 누르기 전 땅에서 잰다(누른 뒤 재면 절반쯤 빠지고 얕아짐)."""
    d = [o for o in obs["obstacles"] if o.get("hazard") == "drop"]
    assert len(d) >= 12 and max(o["depth_m"] for o in d) >= 2.0


def test_no_virtual_entrance_at_main_gate(obs):
    assert not [f for f in obs["facilities"] if f["type"] == "entrance" and f["name"] == "제주대학교정문" and f["src"].startswith("가상")]
