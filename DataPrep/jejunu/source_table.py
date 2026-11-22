"""구간별 출처표 out/출처표.csv (계획 Task 11). 경로입력(bf-route-input-1)에는 출처 칸이 없어서 옆에 둔다.

칸: seg, item, s0, s1, src. item은 앞뒤 경사·좌우·턱·계단·노면 재질·노면 등급·폭과 장애물·시설 type.
사용: python -I DataPrep/jejunu/source_table.py [--world out/virtual_world.json]
"""
import argparse
import collections
import csv
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import common  # noqa: E402

SLOPE_SRC = "1:1000(2011)·1:1000(2013)·1:1000(2025) 땅 높이(5 m 등고선·표고점, 옹벽 끊김 없는 매끈한 땅)"


def source_table(world) -> list:
    rows = []

    def add(seg, item, s0, s1, src):
        rows.append({"seg": seg, "item": item, "s0": round(float(s0), 2), "s1": round(float(s1), 2), "src": src})
    for s in world["segs"]:
        L = s["len"]
        add(s["id"], "앞뒤 경사", 0, L, SLOPE_SRC)
        for st in s["steps"]:
            add(s["id"], "계단", st["s0"], st["s1"], st["src"])
            add(s["id"], "앞뒤 경사", st["s0"], st["s1"], st["src"])
        for c in s["cross"]:
            add(s["id"], "좌우", c["s0"], c["s1"], c["src"])
        for b in s["bumps"]:
            add(s["id"], "턱", b["s"], b["s"], f"{b['src']}; 자리는 {b.get('where_src', '가상')}")
        for x in s["surf"]:
            add(s["id"], "노면 재질", x["s0"], x["s1"], x["src"])
            add(s["id"], "노면 등급", x["s0"], x["s1"], x.get("grade_src", "가상"))
        add(s["id"], "폭", 0, L, s.get("width_src") or "가상")
    for o in world.get("obstacles", []):
        add(o["seg"], o.get("hazard") and f"hazard:{o['hazard']}" or o["type"], o["s"], o.get("s_end", o["s"]), o.get("src", "가상"))
    for f in world.get("facilities", []):
        add(f["seg"], f["type"], f["s"], f["s"], f.get("src", "가상"))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default=str(common.OUT / "virtual_world.json"))
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    world = json.loads(pathlib.Path(a.world).read_text(encoding="utf-8"))
    rows = source_table(world)
    out = common.OUT / "출처표.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["seg", "item", "s0", "s1", "src"])
        w.writeheader()
        w.writerows(rows)
    kind = collections.Counter()
    for r in rows:
        kind[(r["item"], "가상" if r["src"].startswith("가상") else "근거")] += 1
    print(f"출처표 {len(rows)}줄 -> {out}")
    for item in ("앞뒤 경사", "계단", "턱", "좌우", "노면 재질", "노면 등급", "폭", "entrance"):
        print(f"  {item}: 근거 {kind[(item, '근거')]}, 가상 {kind[(item, '가상')]}")


if __name__ == "__main__":
    main()
