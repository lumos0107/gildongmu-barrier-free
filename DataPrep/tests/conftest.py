"""가상 세계 시험의 공용 준비물. 실제 파일을 읽는다(씨앗 7)."""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]  # Unity 프로젝트
sys.path.insert(0, str(ROOT / "DataPrep"))
BASE = pathlib.Path(r"C:\Users\seungjun\Documents\work\베리어프리")
MAP = ROOT / "Assets/Gildongmu/Minsokchon/Data/minsokchon_map.json"
PACK = BASE / "공통자료/10_관광지지도/측정앱자료/minsokchon_c5ad2ca2ed6f.json"
NET = BASE / "공통자료/10_관광지지도/minsokchon/network.geojson"
OSM = BASE / "공통자료/10_관광지지도/minsokchon/osm_features.geojson"
EVENING_TOOLS = BASE / "Barrier-free-information-gathering-app/tools"

import virtual_world as vw  # noqa: E402


@pytest.fixture(scope="session")
def inp():
    return vw.load_inputs(MAP, PACK, NET, OSM)


@pytest.fixture(scope="session")
def ter(inp):
    return vw.make_terrain(inp.size_m, 7)


@pytest.fixture(scope="session")
def nodes(inp, ter):
    return vw.node_heights(inp, ter)


@pytest.fixture(scope="session")
def profiles(inp, ter, nodes):
    return vw.make_profiles(inp, ter, nodes)


@pytest.fixture(scope="session")
def world(inp):
    return vw.build_world(inp, 7)


@pytest.fixture(scope="session")
def plan(inp):
    return vw.plan_points(inp)


def marks_values(world, plan):
    """계획 지점(계단 밖)의 정답 앞뒤·좌우 값. 계획 지점이 없는 짧은 구간은 가운데 지점(가상 기록과 같음)을 쓰고,
    표시값은 설계도 s로 바꿔 잰다(고리 구간은 뒤집힘)."""
    longs, crosses = [], []
    for s in world["segs"]:
        for p in plan[s["id"]] or [{"mark": round(s["len"] / 2, 1)}]:
            x = vw.to_world(s, p["mark"])
            if vw.in_steps(s, x):
                continue
            longs.append(vw.long_at(s, x))
            crosses.append(vw.cross_deg(s, x))
    return longs, crosses


def _net_to_segs(inp):
    """연결망 선(OSM 한 조각)의 가운데점이 2 m 안에 드는 구간 번호. [(구간, 선 속성)]"""
    import math
    import numpy as np
    m = inp.pack["map"]
    n = 256 * 2 ** m["zoom"]

    def xy(lon, lat):
        s = math.sin(math.radians(lat))
        px = (lon + 180) / 360 * n - m["origin"][0]
        py = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n - m["origin"][1]
        return (px - m["W"] / 2) * m["mpp"], (m["H"] / 2 - py) * m["mpp"]

    lines = [(sg["id"], np.array(sg["p"]).reshape(-1, 2)) for sg in inp.segs]
    out = []
    for f in inp.net["features"]:
        q = np.array([xy(*c) for c in f["geometry"]["coordinates"]])
        d = np.r_[0, np.cumsum(np.hypot(*np.diff(q, axis=0).T))]
        mid = np.array([np.interp(d[-1] / 2, d, q[:, 0]), np.interp(d[-1] / 2, d, q[:, 1])])
        best, bd = None, 2.0
        for sid, pts in lines:
            a, b = pts[:-1], pts[1:]
            ab = b - a
            t = np.clip(((mid - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-9), 0, 1)
            dist = np.hypot(*(a + ab * t[:, None] - mid).T).min()
            if dist < bd:
                best, bd = sid, dist
        if best is not None:
            out.append((best, f["properties"]))
    return out


OSM_MAT = {"asphalt": "asphalt", "dirt": "soil", "gravel": "gravel", "paving_stones": "block"}


@pytest.fixture(scope="session")
def osm_surface_segs(inp):
    tags = {}
    for sid, p in _net_to_segs(inp):
        if p.get("surface") in OSM_MAT:
            tags.setdefault(sid, set()).add(OSM_MAT[p["surface"]])
    return {sid: next(iter(v)) for sid, v in tags.items() if len(v) == 1}


@pytest.fixture(scope="session")
def gravel_nogo_segs(inp):
    return sorted({sid for sid, p in _net_to_segs(inp) if p.get("osm") == "w1292606362"})


@pytest.fixture(scope="session")
def pack(inp):
    return inp.pack


@pytest.fixture(scope="session")
def pack_t(pack):
    import virtual_events as ve
    return ve.test_pack(pack)


@pytest.fixture(scope="session")
def events(world, pack_t, plan):
    import virtual_events as ve
    return ve.make_events(world, pack_t, plan)


@pytest.fixture(scope="session")
def evening():
    return vw._evening(EVENING_TOOLS)


@pytest.fixture(scope="session")
def ri(evening, events, pack_t):
    return evening.route_input(events, pack_t, allow_test=True)


def _seg(world, sid):
    return next(s for s in world["segs"] if s["id"] == sid)


def long_at(world, sid, s):
    return vw.long_at(_seg(world, sid), s)


def in_steps(world, sid, s):
    return vw.in_steps(_seg(world, sid), s)
