"""가중치 경로 결과 보고(2026-11-21, 계획 Task 5): 정문에서 모든 시설 × 세 유형으로
세 길이 얼마나 갈리는지, 시설 판정으로 결과가 어떻게 바뀌었는지, 출입구 확인 분포, 시연 후보를 센다.

    python -I DataPrep/route3_report.py --site all      # → DataPrep/out/가중치/보고_<site>.json, 보고.md
"""
import argparse
import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import route_cost as RC  # noqa: E402
import route_engine as R  # noqa: E402
from legacy_compare import SITES  # noqa: E402

OUT = HERE / "out/가중치"
STATES = ("ok", "uncertain", "none")


def _all_same(rt):
    """same_as는 같은 길 중 앞 순서 첫 길을 가리키므로, 셋이 같으면 둘 다 'fast'."""
    return rt["comfort"]["same_as"] == "fast" and rt["safe"]["same_as"] == "fast"


def summarize(legacy: dict, new: dict) -> dict:
    """legacy: {(도착, 유형): v1 결과}, new: {(도착, 유형): v2 결과} → 보고용 수."""
    modes = sorted({m for _, m in new}, key=R.MODES.index)
    out = {"legacy_counts": {}, "counts": {k: {} for k in R.ROUTE_KEYS}, "changed": [], "differ": {}, "same_zero": {},
           "entry": {}, "demo": []}
    for m in modes:
        keys = [k for k in new if k[1] == m]
        c = collections.Counter(legacy[k]["status"] for k in keys)
        out["legacy_counts"][m] = {s: c.get(s, 0) for s in STATES}
        for rk in R.ROUTE_KEYS:
            c = collections.Counter(new[k]["routes"][rk]["status"] for k in keys)
            out["counts"][rk][m] = {s: c.get(s, 0) for s in STATES}
        same = [k for k in keys if _all_same(new[k]["routes"])]
        zero = [k for k in same if not any(new[k]["routes"][rk]["breakdown"] for rk in ("comfort", "safe"))]
        len20 = 0
        for k in keys:
            ls = [new[k]["routes"][rk]["length_m"] for rk in R.ROUTE_KEYS]
            if min(ls) > 0 and max(ls) / min(ls) > 1.2:
                len20 += 1
        out["differ"][m] = {"all_same": len(same), "any_diff": len(keys) - len(same), "len20": len20}
        out["same_zero"][m] = len(zero)
        out["entry"][m] = dict(collections.Counter(new[k]["entry"]["state"] for k in keys))
    for (to, m), r in sorted(new.items(), key=lambda t: (R.MODES.index(t[0][1]), t[0][0])):
        before, after = legacy[(to, m)]["status"], r["routes"]["fast"]["status"]
        if before != after:
            why = []
            fast = r["routes"]["fast"]
            src = [b["reasons"] for b in fast["blocked_by"]] if after == "none" else \
                [x["reasons"] for x in fast.get("steps", []) if x["state"] == "uncertain"]
            for rs in src:
                why += [x for x in rs if x not in why]
            out["changed"].append([to, m, before, after, why])
        rt = r["routes"]
        if any(rt[rk]["same_as"] for rk in R.ROUTE_KEYS):
            continue
        ov = [rt["fast"]["overlap"].get("comfort", 1.0), rt["fast"]["overlap"].get("safe", 1.0),
              rt["comfort"]["overlap"].get("safe", 1.0)]
        if max(ov) < 0.8:
            out["demo"].append({"to": to, "mode": m, "status": rt["fast"]["status"],
                                "lengths": {rk: rt[rk]["length_m"] for rk in R.ROUTE_KEYS}, "overlap_max": max(ov)})
    out["demo"].sort(key=lambda d: d["overlap_max"])
    return out


def run(site: str, weights) -> dict:
    ri, pack, fac, start, _ = SITES[site]
    ctx_old, facs = R.load(ri, pack, fac)
    ctx_new, _ = R.load(ri, pack, fac, facility_rules=True)
    legacy, new = {}, {}
    for f in facs:
        if f["name"] == start:
            continue
        for m in R.MODES:
            legacy[(f["name"], m)] = R.route_by_names(ctx_old, facs, start, f["name"], m)
            new[(f["name"], m)] = R.route3_by_names(ctx_new, facs, start, f["name"], m, weights)
    s = summarize(legacy, new)
    s.update(site=site, start=start, n_dest=len(facs) - 1, weights_version=weights.get("version"))
    return s


KO = {"manual": "수동휠체어", "power": "전동휠체어", "stroller": "유아차"}
ST_KO = {"ok": "갈 수 있음", "uncertain": "불확실", "none": "갈 수 없음", "blocked": "막힘", "unknown": "모름", "na": "해당 없음"}


def to_md(reps: list) -> str:
    L = ["# 가중치 경로 결과 보고(가상 자료)", "",
         "정문에서 모든 시설로, 세 유형 × 세 길. 숫자는 가상 값으로 계산한 것이라 실측 뒤 바뀐다. "
         f"가중치 {reps[0]['weights_version']}(`DataPrep/route_weights.json`).", ""]
    for i, s in enumerate(reps, 1):
        L += [f"## {i}. {s['site']} ({s['start']}에서 {s['n_dest']}곳)", "",
              "가. 도달 수(갈 수 있음 / 불확실 / 갈 수 없음). 세 길은 같은 판정·단계를 써서 수가 같다.", "",
              "| 유형 | 지금 판정(legacy) | 시설 판정 넣은 뒤 |", "|---|---|---|"]
        for m, c in s["legacy_counts"].items():
            n = s["counts"]["fast"][m]
            L.append(f"| {KO[m]} | {c['ok']} / {c['uncertain']} / {c['none']} | {n['ok']} / {n['uncertain']} / {n['none']} |")
        L += ["", f"나. 시설 판정으로 결과가 바뀐 곳 {len(s['changed'])}건", ""]
        if s["changed"]:
            L += ["| 도착 | 유형 | 전 | 후 | 바뀐 뒤 이유 |", "|---|---|---|---|---|"]  # 갈 수 없음이면 막힌 이유, 확인 필요면 확인 필요 이유
            L += [f"| {to} | {KO[m]} | {ST_KO[a]} | {ST_KO[b]} | {', '.join(w) or '-'} |" for to, m, a, b, w in s["changed"]]
        L += ["", "다. 세 길이 갈리는 정도", "", "| 유형 | 세 길 모두 같음(그중 벌점 0) | 하나라도 다름 | 길이 20% 넘게 차이 |",
              "|---|---|---|---|"]
        for m, d in s["differ"].items():
            L.append(f"| {KO[m]} | {d['all_same']}({s['same_zero'][m]}) | {d['any_diff']} | {d['len20']} |")
        L += ["", "세 길이 모두 같은데 벌점이 있는 경우의 원인(대안 길 없음 / 한 길이 모든 면에서 나음 / 가중치 차이 작음)은 나누지 않았다.",
              "", "라. 출입구 확인", "", "| 유형 | 분포 |", "|---|---|"]
        for m, e in s["entry"].items():
            L.append(f"| {KO[m]} | " + ", ".join(f"{ST_KO.get(k, k)} {v}" for k, v in sorted(e.items())) + " |")
        L += ["", f"마. 시연 후보(세 길이 서로 다르고 서로 겹침이 80% 미만) {len(s['demo'])}건, 겹침이 적은 순 앞 10건", "",
              "| 도착 | 유형 | 판정 | 빠른 / 편한 / 안전한 길이(m) | 가장 큰 겹침 |", "|---|---|---|---|---|"]
        for d in s["demo"][:10]:
            ln = d["lengths"]
            L.append(f"| {d['to']} | {KO[d['mode']]} | {ST_KO[d['status']]} | {ln['fast']:.0f} / {ln['comfort']:.0f} / "
                     f"{ln['safe']:.0f} | {d['overlap_max']:.2f} |")
        L.append("")
    L += ["## 알아 둘 점", "",
          "- 같은 구간을 출발·도착이 함께 쓰고 바깥으로 돌아가는 길에서는 불확실 벌점·막힌 수를 한 구간에 두 번 셀 수 있다(계획 '검토 반영').",
          "- 쉴 곳 없는 긴 오르막은 한 구간 안에서만 본다(여러 구간에 걸친 30 m는 보지 않는 근사).", ""]
    return "\n".join(L)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="가중치 경로 결과 보고")
    ap.add_argument("--site", choices=list(SITES) + ["all"], default="all")
    ap.add_argument("--weights", default=str(HERE / "route_weights.json"))
    a = ap.parse_args(argv)
    wt = RC.load_weights(a.weights)
    OUT.mkdir(parents=True, exist_ok=True)
    reps = []
    for site in (list(SITES) if a.site == "all" else [a.site]):
        s = run(site, wt)
        (OUT / f"보고_{site}.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
        reps.append(s)
        print(f"{site}: 바뀐 곳 {len(s['changed'])}, 시연 후보 {len(s['demo'])}, " +
              ", ".join(f"{m} {c['ok']}/{c['uncertain']}/{c['none']}" for m, c in s["counts"]["fast"].items()))
    (OUT / "보고.md").write_text(to_md(reps), encoding="utf-8")
    print(f"저장: {OUT / '보고.md'}")


if __name__ == "__main__":
    main()
