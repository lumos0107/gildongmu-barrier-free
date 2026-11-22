"""경로 추천 앱 첫 판(route_engine.py) 시험. 설계: Docs/2026-11-15-경로앱-설계.md"""
import pathlib

import pytest

from conftest import PACK

from route_engine import judge


def seg(values=(), barriers=(), surfaces=(), status="done", missing=(), L=20.0):
    return {"seg": 1, "len": L, "status": status, "missing": list(missing), "values": list(values),
            "barriers": list(barriers), "surfaces": list(surfaces)}


def v(long, s=10.0, cross=0.0, unc=()):
    return {"s": s, "long": long, "cross": cross, "uncertain_for": list(unc)}


def b(t, s=10.0, value=None, unc=(), s_end=None):
    return {"type": t, "s": s, "s_end": s_end, "route_value": value, "uncertain_for": list(unc), "unmeasured": False}


# ── Task 1: 판정 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("long,want", [(4.4, "ok"), (4.6, "uncertain"), (-4.9, "uncertain"), (5.1, "blocked")])
def test_slope_manual(long, want):
    assert judge(seg([v(long)]), "manual").state == want


@pytest.mark.parametrize("long,want", [(5.4, "ok"), (5.6, "uncertain"), (-5.9, "uncertain"), (6.0, "blocked")])
def test_slope_power(long, want):
    assert judge(seg([v(long)]), "power").state == want


def test_slope_stroller():
    a, c = judge(seg([v(8.0)]), "stroller"), judge(seg([v(4.0)]), "stroller")
    assert a.state == "ok" and c.state == "ok" and a.cost > c.cost


@pytest.mark.parametrize("mm,want", [(17, "ok"), (18, "uncertain"), (22, "uncertain"), (23, "blocked")])
def test_bump(mm, want):
    assert all(judge(seg(barriers=[b("bump", value=mm)]), m).state == want for m in ("manual", "power", "stroller"))


@pytest.mark.parametrize("t", ["steps", "nogo", "broken"])
def test_steps_nogo_broken(t):
    assert all(judge(seg(barriers=[b(t)]), m).state == "blocked" for m in ("manual", "power", "stroller"))


def test_temp_block_note_only():
    j = judge(seg(barriers=[b("temp_block")]), "manual")
    assert j.state == "ok" and j.notes


def test_surface_very_bad():
    s = seg(surfaces=[{"s": 0.0, "grade": "very_bad", "material": "gravel"}])
    base = judge(seg(), "power").cost
    assert judge(s, "manual").state == "blocked"
    assert all(judge(s, m).state == "ok" and judge(s, m).cost > base for m in ("power", "stroller"))


# ── 두 번째 판(11/15 팀 결정): 틈, 실측 자료의 노면 '못 감' ──────────────────
def gap(value, direction="parallel", remain=0, s=10.0, unmeasured=False):
    return {"type": "gap", "s": s, "s_end": None, "value": value, "dir": direction, "remain_cm": remain,
            "route_value": None, "uncertain_for": [], "unmeasured": unmeasured}


@pytest.mark.parametrize("mm,want", [(9, "ok"), (10, "uncertain"), (13, "uncertain"), (14, "blocked")])
def test_gap_parallel(mm, want):
    """진행 방향과 나란한 틈: 13 mm 넘으면 막힘, 10~13 mm 불확실(세 유형 같음, 미국 장애인법 13 mm)."""
    assert all(judge(seg(barriers=[gap(mm)]), m).state == want for m in ("manual", "power", "stroller"))


def test_gap_cross_not_judged():
    assert judge(seg(barriers=[gap(25, direction="cross")]), "manual").state == "ok"


@pytest.mark.parametrize("direction", [None, ""])
def test_gap_missing_direction_is_parallel(direction):
    """방향이 빈 틈(없음, 빈 글자)은 나란함으로 본다(매뉴얼: 비스듬하면 나란함으로 적음)."""
    assert judge(seg(barriers=[gap(25, direction=direction)]), "manual").state == "blocked"


@pytest.mark.parametrize("remain,want", [(80, "ok"), (79, "blocked"), (None, "blocked")])
def test_gap_avoidable(remain, want):
    """틈을 피해 이어지는 남은 폭이 80 cm 이상이면 막지 않는다(못 잰 남은 폭은 피할 수 없다고 본다)."""
    assert judge(seg(barriers=[gap(25, remain=remain)]), "manual").state == want


def test_gap_unknown_width():
    assert judge(seg(barriers=[gap(None)]), "manual").state == "uncertain"
    assert judge(seg(barriers=[gap(25, unmeasured=True)]), "manual").state == "uncertain"


def test_gap_outside_range_ignored():
    assert judge(seg(barriers=[gap(25, s=15.0)]), "manual", 0.0, 10.0).state == "ok"


def test_very_bad_unchecked_is_uncertain():
    """실측 자료에서 노면 등급 기준을 밀어 보기로 확인하기 전에는 '못 감'으로 막지 않고 불확실(측정 매뉴얼 10장)."""
    s = seg(surfaces=[{"s": 0.0, "grade": "very_bad", "material": "gravel"}])
    j = judge(s, "manual", very_bad_blocks=False)
    assert j.state == "uncertain" and any("밀어 보기" in r for r in j.reasons)
    assert judge(s, "manual").state == "blocked"  # 기본(가상 자료)은 전처럼 막힘


def test_ctx_surface_rule():
    """가상 자료(test)이거나 확인 표시(surface_checked)가 있으면 막고, 실측 자료에 표시가 없으면 불확실."""
    from route_engine import find_route
    vb = {"surfaces": [{"s": 0.0, "grade": "very_bad", "material": "gravel"}]}
    ctx = make_ctx({11: vb, 13: vb})
    assert find_route(ctx, (10, 0.0), (11, 10.0), "manual")["status"] == "none"
    ctx.test = False
    assert find_route(ctx, (10, 0.0), (11, 10.0), "manual")["status"] == "uncertain"
    ctx.surface_checked = True
    assert find_route(ctx, (10, 0.0), (11, 10.0), "manual")["status"] == "none"


@pytest.mark.parametrize("cm,want", [(79, "blocked"), (85, "uncertain"), (90, "ok")])
def test_width(cm, want):
    assert judge(seg(barriers=[b("width_rep", s=1.0, value=cm)]), "manual").state == want
    assert judge(seg(barriers=[b("narrow", value=cm)]), "stroller").state == want


def test_status_not_done():
    assert judge(seg(status="partial"), "manual").state == "uncertain"
    assert judge(seg(missing=["slope"]), "manual").state == "uncertain"


def test_uncertain_for():
    assert judge(seg([v(1.0, unc=["power"])]), "power").state == "uncertain"
    assert judge(seg([v(1.0, unc=["power"])]), "manual").state == "ok"


def test_cross_null():
    j = judge(seg([v(1.0, cross=None)]), "manual")
    assert j.state == "ok" and any("좌우" in n for n in j.notes)


def test_partial_range():
    s = seg(barriers=[b("bump", s=15.0, value=23)])
    assert judge(s, "manual", 0.0, 8.0).state == "ok"
    assert judge(s, "manual", 0.0, 16.0).state == "blocked"


# ── Task 2: 길 찾기 ─────────────────────────────────────────────────────────
#   1 ─10─ 2 ─11─ 3      (10 m씩)
#   1 ─12─ 4 ─13─ 3      (15 m씩),  고리 20: 3 → 3 (30 m)
def make_ctx(extra=None):
    from route_engine import Ctx
    g = {10: (1, 2, 10.0), 11: (2, 3, 10.0), 12: (1, 4, 15.0), 13: (4, 3, 15.0), 20: (3, 3, 30.0)}
    segs = {k: {"a": a, "b": c, "len": L} for k, (a, c, L) in g.items()}
    items = {k: seg(L=L) | {"seg": k} for k, (_, _, L) in g.items()}
    for k, kw in (extra or {}).items():
        items[k] = seg(L=g[k][2], **kw) | {"seg": k}
    return Ctx(segs=segs, items=items, test=True, site="test")


def test_shortest_ok():
    from route_engine import find_route
    r = find_route(make_ctx(), (10, 0.0), (11, 10.0), "manual")
    assert r["found"] and r["status"] == "ok" and [x["seg"] for x in r["steps"] if x["s0"] != x["s1"]] == [10, 11]
    assert abs(r["length_m"] - 20.0) < 1e-6


def test_avoid_blocked():
    from route_engine import find_route
    r = find_route(make_ctx({11: {"barriers": [b("steps", s=5.0)]}}), (10, 0.0), (11, 10.0), "manual")
    assert r["status"] == "ok" and 11 not in [x["seg"] for x in r["steps"] if x["s0"] != x["s1"]]
    assert abs(r["length_m"] - 30.0) < 1e-6


def test_uncertain_fallback():
    from route_engine import find_route
    r = find_route(make_ctx({11: {"barriers": [b("bump", s=5.0, value=20)]}, 13: {"barriers": [b("steps", s=5.0)]}}),
                   (10, 0.0), (11, 10.0), "manual")
    assert r["found"] and r["status"] == "uncertain" and r["uncertain_segs"] == 1


def test_none_reports_blockers():
    from route_engine import find_route
    r = find_route(make_ctx({11: {"barriers": [b("steps", s=5.0)]}, 13: {"barriers": [b("steps", s=5.0)]}}),
                   (10, 0.0), (11, 10.0), "manual")
    assert not r["found"] and r["status"] == "none"
    assert r["blocked_by"] and all("계단" in x["reasons"] for x in r["blocked_by"])


def test_same_segment():
    from route_engine import find_route
    r = find_route(make_ctx(), (12, 2.0), (12, 10.0), "manual")
    assert r["found"] and len(r["steps"]) == 1 and r["steps"][0]["seg"] == 12
    assert (r["steps"][0]["s0"], r["steps"][0]["s1"]) == (2.0, 10.0) and abs(r["length_m"] - 8.0) < 1e-6


def test_loop_segment():
    from route_engine import find_route
    r = find_route(make_ctx(), (20, 10.0), (10, 0.0), "manual")
    assert r["found"] and r["steps"][0]["seg"] == 20 and r["steps"][0]["s1"] == 0.0
    assert abs(r["length_m"] - (10 + 20)) < 1e-6


def test_partial_segment_judgement():
    from route_engine import find_route
    r = find_route(make_ctx({11: {"barriers": [b("bump", s=8.0, value=23)]}}), (11, 2.0), (10, 0.0), "manual")
    assert r["status"] == "ok" and r["steps"][0]["seg"] == 11 and r["steps"][0]["s1"] == 0.0


# ── Task 3: 실제 자료 · CLI ─────────────────────────────────────────────────
FACS = PACK.parent.parent / "minsokchon/시설목록.geojson"


@pytest.fixture(scope="module")
def real(ri, tmp_path_factory):
    import json
    from route_engine import load
    f = tmp_path_factory.mktemp("route") / "경로입력.json"
    f.write_text(json.dumps(ri, ensure_ascii=False), encoding="utf-8")
    return (f,) + load(f, PACK, FACS)


@pytest.mark.parametrize("mode", ["manual", "power", "stroller"])
def test_real_gate_to_toilet3(real, mode):
    from route_engine import route_by_names
    _, ctx, facs = real
    r = route_by_names(ctx, facs, "정문", "화장실 3(한복체험장 옆)", mode)
    assert r["format"] == "bf-route-result-1" and r["test"] is True and r["mode"] == mode and r["found"]
    assert r["from"]["name"] == "정문" and r["to"]["seg"] == r["steps"][-1]["seg"]
    assert all(a["n1"] == b["n0"] for a, b in zip(r["steps"], r["steps"][1:]))


@pytest.mark.parametrize("mode", ["manual", "power", "stroller"])
def test_real_judgement_matches_input(real, mode):
    from route_engine import judge, route_by_names
    _, ctx, facs = real
    r = route_by_names(ctx, facs, "매표소", "소우주카페", mode)
    assert r["steps"]
    for x in r["steps"]:
        assert judge(ctx.items[x["seg"]], mode, x["s0"], x["s1"]).state == x["state"], x


def test_facility_on_missing_segment(real):
    from route_engine import route_by_names
    _, ctx, facs = real
    fake = [dict(facs[0], name="없는 구간 시설", no=999, seg=99999)]
    with pytest.raises(ValueError, match="99999"):
        route_by_names(ctx, facs + fake, "정문", "없는 구간 시설", "manual")


TOILET3 = "화장실 3(한복체험장 옆)"
VIRTUAL_SRC = "가상(계단 없는 출입구)"


def test_virtual_facility_src_in_result(real):
    """시설 목록에 출처(src)가 있으면 결과 from/to에 옮기고, '가상'으로 시작하면 안내를 단다
    (11/15 팀 결정, 제주대 계단 없는 출입구는 모두 가상)."""
    from route_engine import route_by_names
    _, ctx, facs = real
    facs2 = [dict(f, src=VIRTUAL_SRC) if f["name"] == TOILET3 else f for f in facs]
    r = route_by_names(ctx, facs2, "정문", TOILET3, "power")
    assert r["to"]["src"] == VIRTUAL_SRC and "src" not in r["from"]
    assert [n for n in r["notes"] if "자리는 가상" in n] == [f"도착 '{TOILET3}' 자리는 {VIRTUAL_SRC}, 실측 전"]


def test_no_src_result_unchanged(real):
    """출처 칸이 없는 시설 목록(민속촌)이면 결과에 src 칸도 가상 안내도 없다."""
    from route_engine import route_by_names
    _, ctx, facs = real
    r = route_by_names(ctx, facs, "정문", TOILET3, "power")
    assert "src" not in r["from"] and "src" not in r["to"] and not any("자리는 가상" in n for n in r["notes"])


def test_cli_prints_virtual_note(real, tmp_path):
    import json
    import subprocess
    import sys as _sys
    f, _, _ = real
    fc = json.loads(FACS.read_text(encoding="utf-8"))
    for x in fc["features"]:
        if x["properties"]["name"] == TOILET3:
            x["properties"]["src"] = VIRTUAL_SRC
    fp = tmp_path / "시설.geojson"
    fp.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    eng = pathlib.Path(__file__).resolve().parents[1] / "route_engine.py"
    res = subprocess.run([_sys.executable, "-I", str(eng), "--input", str(f), "--pack", str(PACK), "--facilities", str(fp),
                          "--from", "정문", "--to", TOILET3, "--mode", "power", "--out", str(tmp_path / "r.json")],
                         capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, res.stderr
    assert f"자리는 {VIRTUAL_SRC}, 실측 전" in res.stdout


def test_cli_writes_result(real, tmp_path):
    import json
    import subprocess
    import sys as _sys
    f, _, _ = real
    out = tmp_path / "r.json"
    eng = pathlib.Path(__file__).resolve().parents[1] / "route_engine.py"
    res = subprocess.run([_sys.executable, "-I", str(eng), "--input", str(f), "--pack", str(PACK), "--facilities", str(FACS),
                          "--from", "13", "--to", "화장실 3(한복체험장 옆)", "--mode", "power", "--out", str(out)],
                         capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, res.stderr
    r = json.loads(out.read_text(encoding="utf-8"))
    assert r["format"] == "bf-route-result-1" and r["mode"] == "power" and r["from"]["name"] == "정문"


def test_cross_unknown_counts_summed():
    """'좌우 모름' 안내는 구간마다 따로 세지 않고 길 전체 지점 수를 더해 하나로 적는다(같은 문장이 겹쳐 빠지지 않게)."""
    from route_engine import find_route
    nulls = {"values": [v(1.0, s=5.0, cross=None)]}
    r = find_route(make_ctx({10: nulls, 11: nulls}), (10, 0.0), (11, 10.0), "manual")
    assert [n for n in r["notes"] if "좌우" in n] == ["좌우 모름 2지점"]


# ── 최종 검토 고침(11/15) ────────────────────────────────────────────────────
def test_surface_second_direction():
    """둘째 마디에서 출발해 잰 구간(second, 고리 포함)은 노면 기록이 자기 s보다 아래쪽(앞 기록 s까지)을 덮는다."""
    sd = seg(surfaces=[{"s": 20.0, "grade": "good"}, {"s": 8.0, "grade": "very_bad"}]) | {"second": True}
    assert judge(sd, "manual", 0.0, 5.0).state == "blocked"
    assert judge(sd, "manual", 10.0, 20.0).state == "ok"


def test_surface_forward_end_record_covers_nothing():
    fw = seg(surfaces=[{"s": 0.0, "grade": "good"}, {"s": 20.0, "grade": "very_bad"}])
    assert judge(fw, "manual", 0.0, 20.0).state == "ok"


def test_span_barrier_reversed():
    """뒤집혀 적힌 이어지는 장벽(s > s_end)도 범위를 바르게 본다."""
    assert judge(seg(barriers=[b("nogo", s=8.0, s_end=3.0)]), "manual", 0.0, 5.0).state == "blocked"


def test_start_on_node_not_judged():
    """출발 · 도착이 마디 위(s = 0 또는 끝)면 길이 0인 조각을 판정하지 않는다."""
    from route_engine import find_route
    r = find_route(make_ctx({10: {"values": [v(5.1, s=0.5)]}}), (10, 0.0), (12, 15.0), "manual")
    assert r["found"] and r["status"] == "ok" and [x["seg"] for x in r["steps"]] == [12]


@pytest.mark.parametrize("status,blocked,want", [("no_entry", None, "blocked"), ("not_path", None, "blocked"),
                                                 ("done", "no_entry", "blocked"), ("temp_block", None, "ok")])
def test_segment_closed(status, blocked, want):
    j = judge(seg(status=status) | {"blocked": blocked}, "manual")
    assert j.state == want
    if status == "temp_block":
        assert j.notes


def test_record_without_s():
    """위치(s)가 빈 장벽은 구간 전체에 걸친 것으로 보고, s가 빈 노면 기록은 건너뛴다(멈추지 않음)."""
    assert judge(seg(barriers=[b("steps", s=None)]), "manual", 0.0, 3.0).state == "blocked"
    assert judge(seg(surfaces=[{"s": None, "grade": "very_bad"}]), "manual").state == "ok"
