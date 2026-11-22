import json

import pytest

from common import Geo, SITE_DIR, campus_zone, load_1000, new_buildings, shape_of


def test_load_1000_counts(feats):
    assert len(feats) == 17480
    z = campus_zone()
    ins = [x for x in feats if x["code"] == "C0390000" and shape_of(x).intersects(z)]
    assert len(ins) == 108
    assert {x["src"] for x in feats} == {"1:1000(2011)", "1:1000(2013)", "1:1000(2025)"}


def test_geo_roundtrip():
    g = Geo(json.loads((SITE_DIR / "aerial_z19.json").read_text(encoding="utf-8")))
    lon, lat = 126.56169, 33.45500
    x, y = g.to5186(lon, lat)
    assert abs(x - 159250) < 2 and abs(y - 95800) < 2
    ux, uz = g.unity(*g.px(lon, lat))
    assert g.from_unity(ux, uz) == pytest.approx((x, y), abs=0.05)


def test_full_aerial_same_extent():
    a = Geo(json.loads((SITE_DIR / "aerial_z19.json").read_text(encoding="utf-8")))
    b = Geo(json.loads((SITE_DIR / "aerial_z19_full.json").read_text(encoding="utf-8")))
    assert a.size_m == pytest.approx(b.size_m, abs=1.0)


def test_new_buildings_six(feats):
    assert len(new_buildings(feats, campus_zone(0))) == 6
