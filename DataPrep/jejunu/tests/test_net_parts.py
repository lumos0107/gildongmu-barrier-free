import pytest
from shapely.geometry import LineString

from conftest import BIG, part, rec1000
from net_parts import entrances, mark_walkable, sidewalks, stairs


def test_sidewalk_offset_away_from_road():
    road = part(LineString([(0, 0), (100, 0)]), width=8.0)
    curb = rec1000("A0033320", [(0, 4), (100, 4)], 폭="2.0", 재질="블록")
    sw = sidewalks([curb], BIG, [road])[0]
    assert sw["geom"].interpolate(0.5, normalized=True).y == pytest.approx(5.0, abs=0.05)
    assert sw["props"]["surface"] == "block"


def test_road_with_sidewalk_not_walkable():
    road = part(LineString([(0, 0), (100, 0)]), width=8.0)
    lonely = part(LineString([(0, 50), (100, 50)]), width=6.0)
    mark_walkable([road, lonely], sidewalks([rec1000("A0033320", [(0, 4), (100, 4)], 폭="2.0", 재질="블록")], BIG, [road]))
    assert road["props"]["walk"] is False and lonely["props"]["walk"] is True


def test_stair_centerline_long_axis():
    st = stairs([rec1000("C0390000", [[(0, 0), (2, 0), (2, 6), (0, 6), (0, 0)]], 구조="계단", 폭="2.0")], BIG)[0]
    assert st["geom"].length == pytest.approx(6.0, abs=0.1) and st["props"]["width"] == pytest.approx(2.0, abs=0.05)


def test_stand_is_not_path():
    assert stairs([rec1000("C0390000", [[(0, 0), (9, 0), (9, 3), (0, 3), (0, 0)]], 구조="스탠드", 폭="9")], BIG) == []


def test_stepfree_entrance_for_named_building():
    bld = rec1000("B0010000", [[(0, 10), (20, 10), (20, 30), (0, 30), (0, 10)]], 주기="공과대학1호관", 명칭="제주대학교")
    st = stairs([rec1000("C0390000", [[(8, 7), (12, 7), (12, 9.5), (8, 9.5), (8, 7)]], 구조="계단", 폭="4")], BIG)
    walk = [part(LineString([(-10, 5), (30, 5)]), kind="sidewalk")]
    parts, pts = entrances([bld], BIG, st, walk, [])
    kinds = sorted(p["kind"] for p in pts)
    assert kinds == ["stepfree", "steps"]
    assert [p["src"] for p in pts if p["kind"] == "stepfree"][0].startswith("가상")


def test_entrance_stair_runs_toward_wall():
    """건물 앞 넓은 계단(폭 4 m, 깊이 2.5 m)은 벽에 수직으로 오른다(긴 방향이 아님)."""
    bld = rec1000("B0010000", [[(0, 10), (20, 10), (20, 30), (0, 30), (0, 10)]], 주기="공과대학1호관")
    st = stairs([rec1000("C0390000", [[(8, 7), (12, 7), (12, 9.5), (8, 9.5), (8, 7)]], 구조="계단", 폭="4"), bld], BIG)[0]
    (x0, y0), (x1, y1) = st["geom"].coords[0], st["geom"].coords[-1]
    assert abs(x1 - x0) < 0.1 and abs(y1 - y0) == pytest.approx(2.5, abs=0.1)
    assert st["props"]["width"] == pytest.approx(4.0, abs=0.1)


def test_free_stair_follows_slope():
    """건물에서 먼 넓은 계단(동서 8 m, 남북 3 m)은 땅이 남북으로 기울면 남북으로 오른다."""
    rec = rec1000("C0390000", [[(0, 0), (8, 0), (8, 3), (0, 3), (0, 0)]], 구조="계단", 폭="8")
    st = stairs([rec], BIG, grad=lambda x, y: (0.0, 0.07))[0]
    (x0, y0), (x1, y1) = st["geom"].coords[0], st["geom"].coords[-1]
    assert abs(x1 - x0) < 0.1 and abs(y1 - y0) == pytest.approx(3.0, abs=0.1)


def test_free_stair_flat_uses_long_axis():
    rec = rec1000("C0390000", [[(0, 0), (8, 0), (8, 3), (0, 3), (0, 0)]], 구조="계단", 폭="8")
    st = stairs([rec], BIG, grad=lambda x, y: (0.0, 0.002))[0]
    assert st["geom"].length == pytest.approx(8.0, abs=0.1)
