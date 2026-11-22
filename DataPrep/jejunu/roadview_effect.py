"""거리뷰 반영 효과 보고(2026-11-21): 기존 판(경로입력_가상.json)과 거리뷰 반영 판(경로입력_가상_거리뷰.json)으로
정문에서 모든 시설 × 세 유형 × 세 길을 찾아 판정 수 · 판정이 바뀐 곳 · 길이 바뀐 곳 · 시연 후보를 견주고,
새 길이 거리뷰로 안 본 가상 턱이나 남은 가상 연석경사로를 지나는지 센다(확인된 곳을 피해 안 본 곳으로 돌아가는지).

    python -I DataPrep/jejunu/roadview_effect.py   → jejunu/out/거리뷰/반영_효과.md, 반영_효과.json
"""
import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import route_cost as RC  # noqa: E402
import route_engine as R  # noqa: E402
import route3_report as RR  # noqa: E402
from legacy_compare import SITES  # noqa: E402

NEW = HERE / "out/경로입력_가상_거리뷰.json"
OLD = HERE.parents[1] / "Docs/backup_20261122/거리뷰반영전/경로입력_가상.json"  # 거리뷰 반영 전 판(2026-11-22 백업)
OUT = HERE / "out/거리뷰"
PAD = 0.5  # 길 위로 보는 여유(m), roadview_points.py와 같음


def unchecked_on(rin: dict, routes: list, pad: float = PAD) -> list:
    """길들이 지나는 범위(±pad)에 있는, 거리뷰로 안 본(unmeasured 아님) 턱과 남은 가상 연석경사로."""
    used = {}
    for r in routes:
        for st in r["steps"]:
            used.setdefault(st["seg"], []).append(sorted((st["s0"], st["s1"])))

    def on(x):
        return x.get("s") is not None and any(a - pad <= x["s"] <= b + pad for a, b in used.get(x.get("seg"), []))

    out = [{"kind": "턱", "seg": x["seg"], "s": x["s"], "virtual": x.get("route_value")}
           for x in rin["barriers"] if x.get("type") == "bump" and not x.get("unmeasured") and on(x)]
    out += [{"kind": "연석경사로", "seg": f["seg"], "s": f["s"], "virtual": f.get("slope")}
            for f in rin["facilities"] if f.get("type") == "curb_ramp" and on(f)]
    return out


def three_all(ri, pack, fac, start, wt) -> dict:
    ctx, facs = R.load(ri, pack, fac, facility_rules=True)
    return {(f["name"], m): R.route3_by_names(ctx, facs, start, f["name"], m, wt)
            for f in facs if f["name"] != start for m in R.MODES}


def main(argv=None):
    import argparse
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default=str(OLD), help="기준 판(기본: 거리뷰 반영 전 백업)")
    ap.add_argument("--new", default=str(NEW), help="견줄 판(기본: 11/21 덧댄 판)")
    ap.add_argument("--tag", default="", help="결과 파일 이름 뒤에 붙임(반영_효과_<tag>.md)")
    a = ap.parse_args(argv)
    _, pack, fac, start, _ = SITES["jejunu1000"]
    ri_old, NEWP = pathlib.Path(a.old), pathlib.Path(a.new)
    wt = RC.load_weights(HERE.parent / "route_weights.json")
    old, new = three_all(ri_old, pack, fac, start, wt), three_all(NEWP, pack, fac, start, wt)
    fast_old = {k: v["routes"]["fast"] for k, v in old.items()}
    s_old, s_new = RR.summarize(fast_old, old), RR.summarize(fast_old, new)
    moved = {rk: sum(1 for k in new if R._path_key(old[k]["routes"][rk]) != R._path_key(new[k]["routes"][rk]))
             for rk in R.ROUTE_KEYS}
    why = collections.Counter(w for _, _, _, _, ws in s_new["changed"] for w in ws)
    rin_new = json.loads(NEWP.read_text(encoding="utf-8"))
    rin_old = json.loads(ri_old.read_text(encoding="utf-8"))
    ramps = [sum(1 for f in r["facilities"] if f["type"] == "curb_ramp") for r in (rin_old, rin_new)]
    applied = {"bumps_unknown": sum(1 for b in rin_new["barriers"] if b["type"] == "bump" and b.get("unmeasured")),
               "curb_ramps_removed": ramps[0] - ramps[1], "old": ri_old.name, "new": NEWP.name}
    un_new = unchecked_on(rin_new, [r for v in new.values() for r in v["routes"].values()])
    un_old = unchecked_on(rin_old, [r for v in old.values() for r in v["routes"].values()])
    old_keys = {(u["kind"], u["seg"], round(u["s"], 2)) for u in un_old}
    fresh = [u for u in un_new if (u["kind"], u["seg"], round(u["s"], 2)) not in old_keys]
    rep = {"n_dest": len({k[0] for k in new}), "counts_old": s_old["counts"]["fast"], "counts_new": s_new["counts"]["fast"],
           "changed": s_new["changed"], "changed_why": why.most_common(), "path_moved": moved,
           "differ_old": s_old["differ"], "differ_new": s_new["differ"], "demo_old": len(s_old["demo"]),
           "demo_new": len(s_new["demo"]), "demo_new_top": s_new["demo"][:10],
           "unchecked_on_new": un_new, "unchecked_fresh": fresh, "n_pairs": len(new), "applied": applied,
           "missing_segs_new": sum(1 for s in rin_new["segments"] if s.get("missing"))}
    name = "반영_효과" + (f"_{a.tag}" if a.tag else "")
    (OUT / f"{name}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / f"{name}.md").write_text(to_md(rep), encoding="utf-8")
    print(to_md(rep))


def to_md(r: dict) -> str:
    KO, ST = RR.KO, RR.ST_KO
    L = ["# 거리뷰 반영 효과(제주대, 가상 자료)", "",
         f"정문에서 {r['n_dest']}곳 × 세 유형 = {r['n_pairs']}쌍, 세 길. 기존 판 = {r['applied']['old']}, "
         f"새 판 = {r['applied']['new']}(거리뷰로 본 턱 {r['applied']['bumps_unknown']}개 '높이 모름', "
         f"가상 연석경사로 {r['applied']['curb_ramps_removed']}개 뺌, '다 재지 못함' 구간 {r['missing_segs_new']}개).", "",
         "## 1. 판정 수(갈 수 있음 / 확인 필요 / 갈 수 없음)", "", "| 유형 | 기존 판 | 새 판 |", "|---|---|---|"]
    for m, c in r["counts_old"].items():
        n = r["counts_new"][m]
        L.append(f"| {KO[m]} | {c['ok']} / {c['uncertain']} / {c['none']} | {n['ok']} / {n['uncertain']} / {n['none']} |")
    L += ["", f"## 2. 판정이 바뀐 곳 {len(r['changed'])}쌍", "", "| 바뀐 뒤 이유 | 쌍 수 |", "|---|---|"]
    L += [f"| {w} | {n} |" for w, n in r["changed_why"][:12]]
    L += ["", "## 3. 길(지나는 구간)이 바뀐 곳", "", "| 길 | 바뀐 쌍 |", "|---|---|"]
    L += [f"| {R.ROUTE_KO[k]} | {n} |" for k, n in r["path_moved"].items()]
    L += ["", "## 4. 세 길이 갈리는 정도", "", "| 유형 | 기존: 모두 같음 / 하나라도 다름 | 새: 모두 같음 / 하나라도 다름 |", "|---|---|---|"]
    for m, d in r["differ_old"].items():
        e = r["differ_new"][m]
        L.append(f"| {KO[m]} | {d['all_same']} / {d['any_diff']} | {e['all_same']} / {e['any_diff']} |")
    L += ["", f"시연 후보(세 길이 서로 다르고 겹침 80% 미만): 기존 {r['demo_old']}건 → 새 {r['demo_new']}건", "",
          "## 5. 새 길이 지나는, 거리뷰로 안 본 곳", "",
          f"- 새 판의 모든 길이 지나는 안 본 가상 턱 · 남은 가상 연석경사로: {len(r['unchecked_on_new'])}곳",
          f"- 그중 기존 판의 길에는 없던 곳(확인된 곳을 피해 새로 지나게 된 곳): {len(r['unchecked_fresh'])}곳", ""]
    if r["unchecked_fresh"]:
        L += ["| 무엇 | 구간 | s(m) | 가상 값 |", "|---|---|---|---|"]
        L += [f"| {u['kind']} | {u['seg']} | {u['s']:.1f} | {u['virtual']} |" for u in r["unchecked_fresh"]]
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    main()
