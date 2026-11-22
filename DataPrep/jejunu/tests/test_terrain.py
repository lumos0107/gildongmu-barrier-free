import math

import numpy as np

from common import campus_zone, load_5000, shape_of
from terrain import height_5186, spot_report


def test_contours_and_spots_kept(ter, geo, feats):
    d = [abs(x) for *_, x in spot_report(ter, geo, [x for x in feats if x["code"] == "F0020000"])]
    assert np.median(d) < 0.5


def test_independent_5000_spots(ter, geo):
    d = [abs(x) for *_, x in spot_report(ter, geo, load_5000("N3P_F0020000", campus_zone()))]
    assert len(d) > 20
    assert np.median(d) < 2.0


def test_wall_makes_step(ter, geo, feats):
    z = campus_zone()
    walls = sorted((x for x in feats if x["code"] == "F0040000" and float(x["attrs"].get("높이") or 0) >= 2.0 and shape_of(x).intersects(z)),
                   key=lambda x: -float(x["attrs"]["높이"]))[:10]
    assert len(walls) == 10
    ok = 0
    for w in walls:
        ln = shape_of(w)
        h = float(w["attrs"]["높이"])
        m, q = ln.interpolate(0.45, normalized=True), ln.interpolate(0.55, normalized=True)
        nx, ny = -(q.y - m.y), q.x - m.x
        k = math.hypot(nx, ny)
        nx, ny = nx / k, ny / k
        a = height_5186(ter, geo, m.x + 1.5 * nx, m.y + 1.5 * ny)
        b = height_5186(ter, geo, m.x - 1.5 * nx, m.y - 1.5 * ny)
        ok += abs(a - b) >= 0.5 * h
    assert ok >= 8
