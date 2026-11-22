import pytest


def test_segs_match_pack(mp, pack):
    assert [s["id"] for s in mp["segs"]] == [s["seg"] for s in pack["segs"]]
    assert all(abs(a["len"] - b["len"]) < 1e-6 for a, b in zip(mp["segs"], pack["segs"]))


def test_surf_spans_cover_segment(mp):
    for s in mp["segs"]:
        sp = sorted(s["surf_src"], key=lambda x: x["s0"])
        assert sp[0]["s0"] == 0 and sp[-1]["s1"] == pytest.approx(s["len"], abs=0.05)
        assert all(abs(a["s1"] - b["s0"]) < 0.05 for a, b in zip(sp, sp[1:]))


def test_buildings_include_new(mp):
    assert sum(1 for b in mp["buildings"] if b["src"] == "브이월드") >= 6


def test_walls_have_height(mp):
    assert mp["walls"] and all(w["h"] > 0 and w["src"].startswith("1:1000") for w in mp["walls"])


def test_kerbs_inside_segment(mp):
    ks = [(s, k) for s in mp["segs"] for k in s["kerbs"]]
    assert len(ks) > 300
    assert all(0 < k["s"] < s["len"] for s, k in ks)


def test_aerial_square_and_matches_size(mp):
    from PIL import Image
    from common import OUT
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(OUT / "aerial.jpg")
    assert im.width == im.height
    assert abs(im.width * mp["mpp"] / 2 - mp["sizeM"]) < 1.0  # 19단계 사진(화소 크기 = 18단계의 절반)이 sizeM을 덮음


def test_kerbs_sit_at_sidewalk_transition(mp):
    """턱 자리 0.9 m 안(구간 끝 턱은 0.8 m 안쪽으로 밀기 때문)에 보도가 아닌 토막(건너는 곳·진출입부·잇기·차도)이 있어야 한다(보도 한가운데 놓이지 않음)."""
    bad = [(s["id"], k["s"]) for s in mp["segs"] for k in s["kerbs"]
           if not any(sp["kind"] != "sidewalk" and sp["s0"] - 0.9 <= k["s"] <= sp["s1"] + 0.9 for sp in s["surf_src"])]
    assert not bad, bad[:10]
