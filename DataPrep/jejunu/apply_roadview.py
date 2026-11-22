"""거리뷰 판정을 제주대 경로 입력에 반영한 새 판을 만든다(2026-11-21 팀 결정 A).

- 거리뷰로 본 연석 넘는 곳(out/거리뷰/판정_합본.json의 '턱')의 가상 턱 높이를 지우고 '높이 모름'(unmeasured)으로 둔다.
  엔진은 이것을 '턱 높이 모름 → 확인 필요'로 판정한다. 가상 값은 virtual에, 거리뷰 판정은 roadview에 남긴다.
  사진 판정(7~10 m 밖, 차 위 카메라)으로는 턱을 낮췄는지 잘 가려지지 않아 '턱 있음'으로 단정하지 않는다.
- 거리뷰에서 연석경사로가 아니라고 본 자리의 가상 연석경사로는 뺀다('연석경사로'·'모름'이면 둔다).
- 기존 파일(경로입력_가상.json)은 고치지 않는다.

    python -I DataPrep/jejunu/apply_roadview.py
    → jejunu/out/경로입력_가상_거리뷰.json, jejunu/out/거리뷰/반영_목록.json
"""
import copy
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
# 2026-11-22부터 out/경로입력_가상.json은 설계도에서 거리뷰를 반영해 만든다(build_world.py). 이 덧대기는 반영 전 판을 읽는다(기록용).
SRC = HERE.parents[1] / "Docs/backup_20261122/거리뷰반영전/경로입력_가상.json"
PTS = (HERE / "out/거리뷰/판정_합본.json", HERE / "out/거리뷰/판정_2차.json")  # 1차 89곳, 2차(반영 뒤 새로 지나게 된 곳)
DST = HERE / "out/경로입력_가상_거리뷰.json"
LIST = HERE / "out/거리뷰/반영_목록.json"
S_TOL = 0.01  # 판정 지점의 s와 경로 입력 s가 같은 자리로 보는 차이(m)
KEEP_RAMP = ("연석경사로", "모름")


def _find(recs, typ, seg, s):
    return next((x for x in recs if x.get("type") == typ and x.get("seg") == seg
                 and x.get("s") is not None and abs(x["s"] - s) <= S_TOL), None)


def apply(rin: dict, points: list, date: str = "2026-11-21") -> tuple:
    """(새 경로 입력, 바뀐 목록). rin은 고치지 않는다."""
    new = copy.deepcopy(rin)
    ch = {"bumps": [], "removed_curb_ramps": [], "missing": []}
    drop = []
    for p in points:
        rv = {"no": p["no"], "shape": p["shape"], "lip": p.get("lip"), "confidence": p.get("confidence")}
        for it in p["items"]:
            if it["kind"] == "턱":
                x = _find(new["barriers"], "bump", it["seg"], it["s"])
                if x is None:
                    ch["missing"].append({"no": p["no"], "kind": "턱", "seg": it["seg"], "s": it["s"]})
                    continue
                x["virtual"] = {"value": x.get("value"), "route_value": x.get("route_value")}
                x["value"] = x["route_value"] = None
                x["unmeasured"] = True
                x["roadview"] = rv
                ch["bumps"].append({"seg": x["seg"], "s": x["s"], "virtual_mm": x["virtual"]["route_value"]} | rv)
            elif it["kind"] == "연석경사로":
                f = _find(new["facilities"], "curb_ramp", it["seg"], it["s"])
                if f is None:
                    ch["missing"].append({"no": p["no"], "kind": "연석경사로", "seg": it["seg"], "s": it["s"]})
                elif p["shape"] not in KEEP_RAMP:
                    drop.append(f)
                    ch["removed_curb_ramps"].append({"seg": f["seg"], "s": f["s"], "slope": f.get("slope"),
                                                     "end_mm": f.get("end_mm")} | rv)
    new["facilities"] = [f for f in new["facilities"] if not any(f is d for d in drop)]
    new["roadview"] = {"date": date, "source": "경로입력_가상.json", "from": "거리뷰/판정_합본.json",
                       "bumps_unknown": len(ch["bumps"]), "curb_ramps_removed": len(ch["removed_curb_ramps"])}
    return new, ch


def load_points() -> list:
    return [p for f in PTS if f.exists() for p in json.loads(f.read_text(encoding="utf-8"))]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    src = json.loads(SRC.read_text(encoding="utf-8"))
    pts = load_points()
    new, ch = apply(src, pts)
    DST.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")  # 원래 판과 같은 모양
    LIST.write_text(json.dumps(ch, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"턱 높이 모름 {len(ch['bumps'])} · 연석경사로 뺌 {len(ch['removed_curb_ramps'])} · 못 찾음 {len(ch['missing'])}")
    print(f"→ {DST.name}, {LIST.name}")


if __name__ == "__main__":
    main()
