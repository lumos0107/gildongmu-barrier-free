import json

from shapely.geometry import LineString

from common import SITE_DIR, campus_zone, load_1000, new_buildings
from conftest import GEO, part
from net_graph import assemble, components, load_parts, lonlat_lines

NET = SITE_DIR / "network.geojson"


def test_snapped_ends_share_key7():
    X, Y = 159000.0, 95500.0
    a = part(LineString([(X, Y), (X + 10, Y)]))
    b = part(LineString([(X + 10.6, Y + 0.3), (X + 20, Y)]))
    lines = lonlat_lines(assemble([a, b]), GEO)
    ends = {l[0] for l in lines} | {l[-1] for l in lines}
    assert len(ends) == 3


def test_split_at_crossing():
    a = part(LineString([(0, 0), (10, 0)]))
    b = part(LineString([(5, -5), (5, 5)]))
    assert len(assemble([a, b])) == 4


def test_unwalkable_road_dropped():
    a = part(LineString([(0, 0), (10, 0)]), walk=False)
    b = part(LineString([(0, 5), (10, 5)]), walk=True)
    assert len(assemble([a, b])) == 1


def test_main_component_share():
    L = components(load_parts(NET))
    assert L[0] / sum(L) >= 0.95


def test_no_path_through_new_buildings():
    nb = new_buildings(load_1000(), campus_zone(0))
    lines = load_parts(NET)
    assert not [p for p in lines for b in nb if p["geom"].crosses(b.buffer(-0.5))]


def test_start_is_a_node():
    s = json.loads((SITE_DIR / "network_summary.json").read_text(encoding="utf-8"))["start"]["lonlat"]
    net = json.loads(NET.read_text(encoding="utf-8"))["features"]
    assert any(c == s for f in net for c in (f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][-1]))


def test_stair_status_missing_piece_is_not_connected():
    """연결망에서 잘려 나간 계단(새 건물 안 등)은 끝이 다른 선에 닿아 있어도 이어진 것으로 치지 않는다."""
    from net_graph import stair_status
    st = part(LineString([(0, 0), (0, 3)]), kind="steps", highway="steps", osm="S1")
    road = part(LineString([(-5, 0), (5, 0)]), kind="sidewalk", highway="footway", osm="R1")
    assert stair_status([st], [road])[0][1] == [False, False]
    road_a = part(LineString([(-5, 0), (0, 0)]), kind="sidewalk", highway="footway", osm="R1")
    road_b = part(LineString([(0, 0), (5, 0)]), kind="sidewalk", highway="footway", osm="R1")
    assert stair_status([st], [road_a, road_b, st])[0][1] == [True, False]


def test_network_stairs_match_status():
    import pathlib
    out = pathlib.Path(__file__).resolve().parent.parent / "out"
    con = json.loads((out / "계단_연결.json").read_text(encoding="utf-8"))
    net = json.loads(NET.read_text(encoding="utf-8"))["features"]
    in_net = {f["properties"]["osm"] for f in net if f["properties"].get("highway") == "steps"}
    kept = {x["osm"] for x in con["loose"] if any(x["ok"])}
    assert kept <= in_net
    assert len(in_net) == con["connected"] + len(kept)


def test_t_junction_from_nearest_point_is_split():
    """잇는 선의 끝을 상대 선 위 가장 가까운 점으로 잡으면(부동소수 오차로 선에서 아주 조금 떨어짐) 그래도 갈림길로 잘라야 한다."""
    import random
    from shapely.ops import nearest_points
    from shapely.geometry import Point
    rng = random.Random(1)
    bad = 0
    for _ in range(200):
        x0, y0 = 159000 + rng.uniform(0, 50), 95500 + rng.uniform(0, 50)
        a = LineString([(x0, y0), (x0 + rng.uniform(20, 60), y0 + rng.uniform(-15, 15))])
        e = Point(x0 + rng.uniform(5, 15), y0 + rng.uniform(5, 15))
        q = nearest_points(e, a)[1]
        if e.distance(q) < 2.0 or min(Point(c).distance(q) for c in a.coords) < 0.5:
            continue  # 붙이기로 없어지는 짧은 선, 상대 선의 끝에 닿는 경우(갈림길 아님)는 뺀다
        out = assemble([part(a), part(LineString([e, q]))])
        if len(out) != 3:
            bad += 1
    assert bad == 0, bad


def test_stair_status_needs_real_node():
    """계단 끝이 다른 선에서 0.3 m 떨어져 있기만 하면 이어진 것이 아니다(실제 마디를 같이 써야 함)."""
    from net_graph import stair_status
    st = part(LineString([(0, 0.3), (0, 3)]), kind="steps", highway="steps", osm="S1")
    road = part(LineString([(-5, 0), (5, 0)]), kind="sidewalk", highway="footway", osm="R1")
    assert stair_status([st], [road, st])[0][1] == [False, False]


def test_entrance_wall_end_not_snapped():
    """출입 선의 벽 쪽 끝은 1 m 안에 다른 길이 있어도 붙이지 않는다(출입구가 엉뚱한 길로 옮겨 가지 않게)."""
    walk = part(LineString([(0, 0), (20, 0)]), kind="sidewalk", highway="footway")
    other = part(LineString([(0, 5.5), (20, 5.5)]), kind="drawn", highway="footway")
    ent = part(LineString([(10, 0), (10, 5.0)]), kind="entrance", highway="footway", wall_end=True)
    out = assemble([walk, other, ent])
    e = [p for p in out if p["props"]["kind"] == "entrance"]
    assert e and any(abs(c[1] - 5.0) < 1e-6 for p in e for c in (p["geom"].coords[0], p["geom"].coords[-1]))
