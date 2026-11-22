def test_every_seg_has_slope_source(rows, world):
    assert {r["seg"] for r in rows if r["item"] == "앞뒤 경사"} == {s["id"] for s in world["segs"]}


def test_virtual_entrances_listed(rows):
    assert any(r["item"] == "entrance" and r["src"].startswith("가상") for r in rows)


def test_every_row_has_known_source(rows):
    heads = ("1:1000", "1:5000", "OSM", "브이월드", "항공사진", "가상", "연결망")
    assert all(r["src"].startswith(heads) for r in rows)


HEADS = ("1:1000(2011)", "1:1000(2013)", "1:1000(2025)", "1:5000(2024)", "OSM", "브이월드", "항공사진", "가상", "연결망")


def test_every_row_starts_with_exact_source(rows):
    bad = [r["src"] for r in rows if not r["src"].startswith(HEADS)]
    assert not bad, sorted(set(bad))[:10]


def test_assumed_widths_are_virtual(world):
    for s in world["segs"]:
        if s["kind"] in ("crossing", "drawn"):
            assert s["width_src"].startswith("가상"), (s["id"], s["kind"], s["width_src"])
