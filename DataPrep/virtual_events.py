"""설계도(virtual_world.json)에서 측정 앱 백업과 같은 모양의 가상 측정 기록을 만들고,
저녁 도구(evening.py)로 경로입력(bf-route-input-1)을 만든다.

가상 기록과 가상 자료 파일(pack)은 test: true다. 실제 pack과 섞으면 저녁 도구가 멈춘다.
나중에 실측하면 가상기록.json 자리에 실제 백업 파일을 넣고 원본 pack으로 저녁 도구를 돌린다.

사용: python -I virtual_events.py --world <virtual_world.json> --pack <원본 pack> --evening <측정앱 저장소>/tools --out <폴더>
"""
import argparse
import copy
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import virtual_world as vw  # noqa: E402

T0 = datetime(2026, 11, 15, 9, 0, 0, tzinfo=timezone(timedelta(hours=9)))


def test_pack(pack: dict) -> dict:
    """test: true로 바꾼 사본. hash는 build_pack.py와 같은 방식으로 다시 계산한다(원본은 그대로)."""
    t = copy.deepcopy({k: v for k, v in pack.items() if k not in ("aerial", "db", "hash")})
    t["test"] = True
    t["hash"] = hashlib.sha256(json.dumps(t, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return t


test_pack.__test__ = False  # pytest가 시험으로 모으지 않게


def bump_event(b: dict, mark: float, loop: bool) -> dict:
    """설계도 턱 하나 → 앱 턱 기록. 설계도에 unread가 있으면(제주대 거리뷰로 본 턱, 2026-11-22) 앱의 '못 잼'처럼
    높이를 비우고 unread: ["value"]로 적는다(저녁 도구는 높이 모름 + 그 구간 '다 재지 못함')."""
    up = (b["dir"] == "up") != loop
    d = {"type": "bump", "mark": mark, "value": b["mm"], "dir": "up" if up else "down", "shape": b["shape"], "repeat": "no"}
    if b["shape"] != "square":
        d["run_mm"] = b["run_mm"]
    if b.get("unread"):
        d["value"] = None
        d["unread"] = ["value"]
    return d


def make_events(world: dict, pack_t: dict, plan: dict, evening_dir=None) -> list:
    """고리 구간(a == b)은 저녁 도구가 둘째 마디 출발로 보므로, 그 방향으로 걸은 것처럼 적는다
    (표시값 m은 설계도 s = len − m, 앞뒤 부호와 턱 방향을 뒤집음). 그래야 경로입력의 s와 값이 설계도와 같다."""
    E = vw._evening(evening_dir)
    rules = pack_t["rules"]
    pseg = {s["seg"]: s for s in pack_t["segs"]}
    ev = []

    def add(kind, data, run=None):
        n = len(ev) + 1
        e = {"id": f"v-{n}", "seq": n, "ord": n, "kind": kind, "at": (T0 + timedelta(seconds=n)).isoformat(),
             "dev": "virtual", "app": "virtual", "site": pack_t["site"], "test": True, "net": pack_t["net"],
             "pack": pack_t["hash"], "rules": pack_t["rules"].get("version"), "data": data}
        if run:
            e["run"] = run
        ev.append(e)
        return e["id"]

    obs_by, fac_by = {}, {}
    for o in world.get("obstacles", []):
        obs_by.setdefault(o["seg"], []).append(o)
    for f in world.get("facilities", []):
        fac_by.setdefault(f["seg"], []).append(f)
    SPAN = ("nogo", "hazard")  # 앱에서 끝 표시값(mark_end)이 있는 것
    slope_r = rules["slope"]

    def r1(x):  # 앱은 표시값(m)과 각도(°)를 소수 한 자리로 받는다
        return round(x, 1)

    def in_ranges(x, rr):  # 앱 calc.js inRanges와 같음(경계 포함)
        return any(lo - 1e-9 <= abs(x) <= hi + 1e-9 for lo, hi in rr)
    for seg in world["segs"]:
        sid, L = seg["id"], seg["len"]
        run = add("run_start", {"seg": sid, "from": seg["a"], "start": 0})
        for o in obs_by.get(sid, []):  # 2·3차 장애물(고리 구간에는 놓지 않음)
            d = {k: v for k, v in o.items() if k not in ("seg", "s", "s_end", "depth_m")}
            d["mark"] = r1(o["s"])
            if o["type"] in SPAN:
                d["mark_end"] = r1(o["s_end"])
            add("barrier", d, run)
        for f in fac_by.get(sid, []):
            d = {k: v for k, v in f.items() if k not in ("seg", "s", "x", "z", "s0", "s1")}
            d["mark"] = r1(f["s"])
            add("facility", d, run)
        add("barrier", {"type": "width_rep", "mark": round(min(1.0, L / 2), 1), "value": seg["width_cm"]}, run)
        loop = vw.is_loop(seg)
        sgn = -1 if loop else 1

        def mark_of(s):  # 설계도 s -> 표시값 (고리면 뒤집힘, 같은 식)
            return r1(vw.to_world(seg, s))

        def value(m):
            x = vw.to_world(seg, m)
            return r1(sgn * vw.long_at(seg, x)), r1(vw.cross_deg(seg, x))

        # 계획 지점이 없는 짧은 구간: 앱은 다음 계획 지점이 없으면 kind "more"로 적는다(app.js)
        pts = plan.get(sid) or [{"mark": r1(L / 2), "kind": "more", "both": False, "cross": True}]
        vals = [value(p["mark"]) for p in pts]
        more = vw.more_points(E, pseg[sid], pts, [v for v, _ in vals], rules)
        for p, (v, c) in sorted(list(zip(pts, vals)) + [(p, value(p["mark"])) for p in more], key=lambda t: t[0]["mark"]):
            # 앱은 계획에서 cross: false인 지점(1순위 구간의 5 m 배수 아닌 곳)에서 좌우를 묻지 않는다 -> 빈 값
            # 앱처럼 앞뒤가 재확인 범위(long_recheck)면 두 번 재고(method both), 좌우가 cross_recheck면 좌우도 두 번
            ask = p.get("cross", True)
            both = p.get("both") or in_ranges(v, slope_r["long_recheck"])
            cross = ([c, c] if in_ranges(c, slope_r["cross_recheck"]) else [c]) if ask else []
            add("slope", {"mark": r1(p["mark"]), "values": [v, v] if both else [v], "method": "both" if both else "one",
                          "cross": cross, "kind": p["kind"]}, run)
        for b in seg["bumps"]:
            add("barrier", bump_event(b, mark_of(b["s"]), loop), run)
        for st in seg["steps"]:
            add("barrier", {"type": "steps", "mark": mark_of(st["s1"] if loop else st["s0"]), "count": st["count"]}, run)
        for x in sorted(seg["surf"], key=lambda x: mark_of(x["s1"] if loop else x["s0"])):
            d = {"mark": mark_of(x["s1"] if loop else x["s0"]), "material": x["material"], "grade": x["grade"]}
            if x["grade"] == "very_bad":
                d["reason"] = x["reason"]
            add("surface", d, run)
        has = seg["bumps"] or seg["steps"] or obs_by.get(sid)
        add("run_end", {"end": L, "result": "ok", "missing": [], "no_barrier": None if has else "checked"}, run)
    return ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", required=True)
    ap.add_argument("--pack", required=True)
    ap.add_argument("--evening", default=str(vw.EVENING_TOOLS))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    world = json.loads(pathlib.Path(a.world).read_text(encoding="utf-8"))
    full = json.loads(pathlib.Path(a.pack).read_text(encoding="utf-8"))
    pack_t = test_pack(full)
    inp = vw.Inputs(segs=world["segs"], pack={k: v for k, v in full.items() if k != "aerial"}, net={}, osm={}, size_m=0.0)
    plan = vw.plan_points(inp, a.evening)
    events = make_events(world, pack_t, plan, a.evening)
    pack_path = out / f"{full['site']}_시험_{pack_t['hash']}.json"
    pack_path.write_text(json.dumps({**pack_t, "aerial": full.get("aerial")}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    rec = out / "가상기록.json"
    rec.write_text(json.dumps({"net": pack_t["net"], "virtual": True, "events": events}, ensure_ascii=False), encoding="utf-8")
    res = subprocess.run([sys.executable, "-I", str(pathlib.Path(a.evening) / "evening.py"), str(rec), "--pack", str(pack_path),
                          "--out", str(out / "저녁"), "--allow-test"], capture_output=True, text=True, encoding="utf-8")
    print(res.stdout.strip())
    if res.returncode != 0:
        print(res.stderr.strip())
        raise SystemExit(res.returncode)
    shutil.copyfile(out / "저녁" / "경로입력.json", out / "경로입력_가상.json")
    print(f"가상 pack {pack_t['hash']}, 기록 {len(events)}건 -> {out / '경로입력_가상.json'}")


if __name__ == "__main__":
    main()
