import json
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
for p in (HERE.parent, HERE.parent.parent):  # DataPrep/jejunu, DataPrep(virtual_world)
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import shapely  # noqa: E402
from shapely.geometry import LineString, Polygon  # noqa: E402

import common  # noqa: E402

BIG = shapely.box(-1e7, -1e7, 1e7, 1e7)


def part(geom, **props):
    p = {"kind": "road_public", "highway": "residential", "width": 5.0, "surface": "asphalt", "src": "시험", "osm": "test"}
    p.update(props)
    return {"geom": geom, "props": p}


def rec1000(code, geom, **attrs):
    if isinstance(geom[0], tuple) and not isinstance(geom[0][0], tuple):
        g, gt = [list(geom)], "L"
    else:
        g, gt = [list(r) for r in geom], "A"
    return {"code": code, "gtype": gt, "geom": g, "attrs": {k: str(v) for k, v in attrs.items()}, "sheet": "test", "src": "1:1000(2013)"}


@pytest.fixture(scope="session")
def geo():
    return common.Geo(json.loads((common.SITE_DIR / "aerial_z19.json").read_text(encoding="utf-8")))


@pytest.fixture(scope="session")
def feats():
    return common.load_1000()


GEO = common.Geo(json.loads((common.SITE_DIR / "aerial_z19.json").read_text(encoding="utf-8")))


@pytest.fixture(scope="session")
def ter(feats, geo):
    import terrain
    return terrain.build_terrain(feats, geo)


PACK_PATH = max(common.PACK_DIR.glob("jejunu1000_*.json"), key=lambda x: x.stat().st_mtime, default=common.PACK_DIR / "jejunu1000_없음.json")
MAP_PATH = common.OUT / "jejunu1000_map.json"


def _load_or_skip(path):
    if not path.exists():
        pytest.skip(f"{path.name} 없음")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def pack():
    p = _load_or_skip(PACK_PATH)
    p.pop("aerial", None)
    return p


@pytest.fixture(scope="session")
def mp():
    return _load_or_skip(MAP_PATH)


WORLD_PATH = common.OUT / "virtual_world.json"
MINSOKCHON_WORLD = pathlib.Path(r"C:\Users\seungjun\Documents\Unity\3dmaptogildongmu\Assets\Gildongmu\Minsokchon\Data\virtual_world.json")


@pytest.fixture(scope="session")
def world():
    return _load_or_skip(WORLD_PATH)


@pytest.fixture(scope="session")
def ter_raw(feats, geo):
    import terrain
    return terrain.build_terrain(feats, geo, walls=False)  # 길 높이는 매끈한 땅에서 정한다(build_world)


@pytest.fixture(scope="session")
def obs(world):
    return {"obstacles": world["obstacles"], "facilities": world["facilities"]}


@pytest.fixture(scope="session")
def fl():
    return _load_or_skip(common.SITE_DIR / "시설목록.geojson")


@pytest.fixture(scope="session")
def rows(world):
    import source_table
    return source_table.source_table(world)
