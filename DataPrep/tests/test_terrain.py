import math

import numpy as np

from virtual_world import make_terrain


def test_terrain_shape(ter, inp):
    assert ter.cell == 2.0 and ter.h.shape == (ter.n, ter.n) and ter.n * ter.cell >= inp.size_m
    assert 3.0 <= ter.h.max() - ter.h.min() <= 12.0


def test_node_continuity(inp, profiles, nodes):
    for s in inp.segs:
        pr = profiles[s["id"]]
        assert abs(pr.h[0] - nodes[s["a"]]) < 1e-6 and abs(pr.h[-1] - nodes[s["b"]]) < 1e-6
        assert abs(pr.s[-1] - s["len"]) < 1e-6


def test_osm_incline(inp, profiles):
    inc = [s for s in inp.segs if s["inc"]]
    assert len(inc) == 44
    ok = 0
    for s in inc:
        want = math.degrees(math.atan(max(s["inc"]) / 100))
        got = math.degrees(math.atan(abs(profiles[s["id"]].h[-1] - profiles[s["id"]].h[0]) / s["len"]))
        ok += abs(got - want) <= 0.5
    assert ok >= 0.9 * len(inc)


def test_seed_reproducible(inp):
    a, b = make_terrain(inp.size_m, 7), make_terrain(inp.size_m, 7)
    assert np.array_equal(a.h, b.h)
