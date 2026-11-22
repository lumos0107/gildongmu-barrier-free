"""가중치 경로 Task 4: 세 길(빠른 · 편한 · 안전한), 같은 길 표시, 출입구 확인, v1 바꾸기, CLI. 설계 3장 가 · 다 · 마."""
import json
import pathlib

import pytest

from route_engine import (Ctx, ROUTE_KEYS, as_v1, entry_for, load, main, route3_by_names, route_overlap,
                          three_routes)
from route_cost import load_weights
from test_route import b, make_ctx, v

HERE = pathlib.Path(__file__).resolve().parents[1]
D = pathlib.Path(r"C:\Users\seungjun\Documents\work\베리어프리\공통자료\10_관광지지도")
WT = load_weights(HERE / "route_weights.json")
M = (HERE / "out/경로입력_가상.json", D / "측정앱자료/minsokchon_c5ad2ca2ed6f.json", D / "minsokchon/시설목록.geojson")
J = (HERE / "jejunu/out/경로입력_가상.json", D / "측정앱자료/jejunu1000_9fe6fdc97b8d.json", D / "jejunu1000/시설목록.geojson")
BASE = HERE / "out/가중치/기준_legacy"


@pytest.fixture(scope="module")
def real_m():
    return load(*M, facility_rules=True)


@pytest.fixture(scope="module")
def real_jeju():
    return load(*J, facility_rules=True)


def used(r):
    return [(x["seg"], x["s0"], x["s1"]) for x in r["steps"]]


def test_three_routes_shape(real_m):
    ctx, facs = real_m
    r = route3_by_names(ctx, facs, "정문", "소우주카페", "manual", WT)
    assert r["format"] == "bf-route-result-2" and r["test"] is True and r["weights_version"] == "2026-11-21a"
    assert set(r["routes"]) == set(ROUTE_KEYS) and len({x["status"] for x in r["routes"].values()}) == 1
    assert r["routes"]["fast"]["same_as"] is None and "entry" in r
    for x in r["routes"].values():
        assert x["cost"] == pytest.approx(x["length_m"] + sum(x["breakdown"].values()), abs=1e-2)


def test_same_as_identical():
    ctx = make_ctx({12: {"barriers": [b("steps", s=5.0)]}})  # 길이 하나(10 → 11)뿐
    r = three_routes(ctx, (10, 0.0), (11, 10.0), "manual", WT)
    assert r["fast"]["same_as"] is None and r["comfort"]["same_as"] == "fast" and r["safe"]["same_as"] == "fast"
    assert r["comfort"]["overlap"]["fast"] == 1.0


def test_three_routes_differ():
    ctx = make_ctx({10: {"values": [v(4.0, s=5.0)]}, 11: {"values": [v(4.0, s=5.0)]}})
    r = three_routes(ctx, (10, 0.0), (11, 10.0), "manual", WT)
    assert [x[0] for x in used(r["fast"])] == [10, 11] and [x[0] for x in used(r["comfort"])] == [12, 13]
    assert r["comfort"]["same_as"] is None and r["comfort"]["overlap"]["fast"] == 0.0


def st(seg, s0, s1):
    return {"seg": seg, "s0": s0, "s1": s1}


def test_overlap_partial():
    a = {"length_m": 20.0, "steps": [st(10, 0.0, 10.0), st(11, 0.0, 10.0)]}
    c = {"length_m": 40.0, "steps": [st(10, 0.0, 10.0), st(12, 0.0, 15.0), st(13, 0.0, 15.0)]}
    assert route_overlap(a, c) == 0.25


def test_overlap_reverse_and_zero():
    a = {"length_m": 10.0, "steps": [st(10, 0.0, 10.0)]}
    c = {"length_m": 10.0, "steps": [st(10, 10.0, 0.0)]}
    z = {"length_m": 0.0, "steps": []}
    assert route_overlap(a, c) == 1.0 and route_overlap(z, z) == 1.0 and route_overlap(a, z) == 0.0


def test_same_as_exact():
    ctx = make_ctx()
    r = three_routes(ctx, (10, 0.0), (11, 10.0), "manual", WT)
    other = dict(r["fast"], steps=[dict(x) for x in r["fast"]["steps"]])
    other["steps"][-1]["s1"] = round(other["steps"][-1]["s1"] - 0.05, 3)
    from route_engine import _path_key
    # 겹침 비율은 2자리로 반올림해 1.0이 되지만, 같은 길 판정(_path_key)은 반올림 없이 다르게 본다
    assert route_overlap(other, r["fast"]) == 1.0 and _path_key(other) != _path_key(r["fast"])


# ── 출입구 확인 ───────────────────────────────────────────────────────────────
def door(name, seg=5, s=3.0, **kw):
    return {"type": "entrance", "name": name, "seg": seg, "s": s, "dest": "door", "door_cm": 110, "sill_mm": 0, **kw}


def ectx(*recs):
    return Ctx(segs={}, items={}, facilities=list(recs))


def fac(name, typ="building", seg=5):
    return {"name": name, "type": typ, "seg": seg}


def test_entry_ok():
    e = entry_for(ectx(door("A동")), fac("A동"), 5, 3.0, "manual")
    assert e["state"] == "ok" and e["door"]["name"] == "A동" and e["candidates"] == 1


@pytest.mark.parametrize("kw,want,why", [({"sill_mm": 30}, "blocked", "문턱 30 mm"), ({"sill_mm": 20}, "uncertain", "문턱 20 mm"),
                                         ({"door_cm": 75}, "blocked", "문 폭 75 cm"), ({"door_cm": 85}, "uncertain", "문 폭 85 cm"),
                                         ({"door_cm": None}, "uncertain", "문 폭 모름")])
def test_entry_door_values(kw, want, why):
    e = entry_for(ectx(door("A동", **kw)), fac("A동"), 5, 3.0, "manual")
    assert e["state"] == want and why in e["reasons"]


def test_entry_steps_before_blocked():
    e = entry_for(ectx(door("A동", steps_before=True)), fac("A동"), 5, 3.0, "manual")
    assert e["state"] == "blocked" and "문 앞 계단" in e["reasons"]


def ramp(name, seg=5, w_cm=120, **sl):
    return {"type": "ramp", "name": name, "seg": seg, "s": 3.0, "dest": "door", "w_cm": w_cm,
            "slope_low": sl.get("lo"), "slope_mid": sl.get("mid"), "slope_top": sl.get("top")}


def test_entry_door_ramp():
    e = entry_for(ectx(door("A동", steps_before=True), ramp("A동", lo=3.0, mid=3.0, top=3.0)), fac("A동"), 5, 3.0, "manual")
    assert e["state"] == "ok"


def test_entry_ramp_other_name_ignored():
    e = entry_for(ectx(door("A동", steps_before=True), ramp("B동", lo=3.0)), fac("A동"), 5, 3.0, "manual")
    assert e["state"] == "blocked"


def test_entry_ramp_keeps_sill():
    e = entry_for(ectx(door("A동", steps_before=True, sill_mm=30), ramp("A동", lo=3.0)), fac("A동"), 5, 3.0, "manual")
    assert e["state"] == "blocked" and "문턱 30 mm" in e["reasons"]


def test_entry_narrow_ramp():
    e = entry_for(ectx(door("A동", steps_before=True), ramp("A동", w_cm=75, lo=3.0)), fac("A동"), 5, 3.0, "manual")
    assert e["state"] == "blocked"


def test_entry_ramp_slope_unknown():
    e = entry_for(ectx(door("A동", steps_before=True), ramp("A동")), fac("A동"), 5, 3.0, "manual")
    assert e["state"] == "uncertain" and "문으로 가는 경사로, 기울기 모름" in e["reasons"]


def test_entry_nearest_first():
    e = entry_for(ectx(door("A동", s=3.5, steps_before=True), door("A동", s=40.0)), fac("A동"), 5, 3.0, "manual")
    assert e["state"] == "blocked" and any(r.startswith("더 나은 출입구: A동") for r in e["reasons"])


def test_entry_unnamed_same_segment():
    e = entry_for(ectx(door("출입구", sill_mm=120, door_cm=70)), fac("드라마 세트장", "시설"), 5, 3.0, "manual")
    assert e["state"] == "blocked" and "이름 없는 출입구, 같은 구간으로 찾음" in e["reasons"]


def test_entry_toilet():
    t = {"type": "toilet", "name": "화장실 1", "seg": 5, "s": 3.0, "dest": "door", "door_cm": 95, "bump_mm": 25,
         "stall": "yes", "lock": "open"}
    e = entry_for(ectx(t), fac("화장실 1", "화장실"), 5, 3.0, "stroller")
    assert e["state"] == "blocked" and "문턱 25 mm" in e["reasons"]
    e = entry_for(ectx(t | {"stall": "no", "bump_mm": 0}), fac("화장실 1", "화장실"), 5, 3.0, "stroller")
    assert e["state"] == "blocked" and "장애인 칸 없음" in e["reasons"]


def test_entry_unknown():
    e = entry_for(ectx(door("A동")), fac("연못", "시설", seg=9), 9, 1.0, "manual")
    assert e["state"] == "unknown" and e["reasons"] == ["출입구 기록 없음"]


def test_entry_na(real_jeju):
    ctx, facs = real_jeju
    for name in ("제주대학교정문", next(f["name"] for f in facs if f["type"] == "bus_stop")):
        f = next(x for x in facs if x["name"] == name)
        assert entry_for(ctx, f, f["seg"], 0.0, "manual")["state"] == "na"


def test_as_v1_roundtrip(real_jeju):
    ctx, facs = real_jeju
    r = route3_by_names(ctx, facs, "제주대학교정문", "자연과학대학", "manual", WT)
    for key in ROUTE_KEYS:
        x = as_v1(r, key)
        assert x["format"] == "bf-route-result-1" and x["site"] == "jejunu1000" and x["from"] == r["from"]
        assert x["to"] == r["to"] and x["steps"] == r["routes"][key]["steps"] and x["status"] == r["routes"][key]["status"]
        assert all(n in x["notes"] for n in r["notes"])


@pytest.mark.parametrize("site", ["minsokchon", "jejunu1000"])
def test_status_preserved_weights_only(site):
    ri, pack, fc = M if site == "minsokchon" else J
    ctx, facs = load(ri, pack, fc)  # 시설 판정 끔
    start = "정문" if site == "minsokchon" else "제주대학교정문"
    base = json.loads((BASE / f"{site}.json").read_text(encoding="utf-8"))
    bad = []
    for key, ref in base.items():
        to, mode = key.rsplit("|", 1)
        r = route3_by_names(ctx, facs, start, to, mode, WT)
        bad += [(key, k) for k, x in r["routes"].items() if x["status"] != ref["status"]]
    assert bad == []


def test_cli_three_writes_four_files(tmp_path, capsys):
    out = tmp_path / "r.json"
    main(["--input", str(M[0]), "--pack", str(M[1]), "--facilities", str(M[2]), "--from", "정문", "--to", "소우주카페",
          "--mode", "power", "--three", "--weights", str(HERE / "route_weights.json"), "--out", str(out)])
    r = json.loads(out.read_text(encoding="utf-8"))
    assert r["format"] == "bf-route-result-2"
    for key in ROUTE_KEYS:
        x = json.loads((tmp_path / f"r_{key}.json").read_text(encoding="utf-8"))
        assert x["format"] == "bf-route-result-1" and x["mode"] == "power"
    text = capsys.readouterr().out
    assert "빠른 길" in text and "편한 길" in text and "안전한 길" in text and "출입구" in text


def test_compare_same_yardstick():
    """최종 검토: 세 길을 같은 잣대(편한 길 · 안전한 길 가중치)로 다시 매긴 부담 · 위험을 함께 낸다."""
    ctx = make_ctx({10: {"values": [v(4.0, s=5.0)]}, 11: {"values": [v(4.0, s=5.0)]}})
    r = three_routes(ctx, (10, 0.0), (11, 10.0), "manual", WT)
    assert r["fast"]["compare"]["comfort"] == pytest.approx(0.8 * 20 * 1.5)  # 빠른 길은 경사 부담이 있음
    assert r["comfort"]["compare"]["comfort"] == 0.0
    assert set(r["fast"]["compare"]) == {"comfort", "safe"}
