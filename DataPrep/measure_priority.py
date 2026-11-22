"""실측 우선 구간(11/15).

출발지에서 시설 목록의 모든 곳으로 가는 길을 이동 유형별로 계산하고, 그 길에서 막힘·불확실로 나온 구간을 하나씩
'재 보니 문제없음'으로 바꿨을 때 결과가 좋아지는(갈 수 없음 → 불확실·갈 수 있음, 불확실 → 갈 수 있음) 목적지 수를 센다.
현장 측정을 어디부터 할지 정하는 참고다. 경로 엔진(route_engine.py)은 고치지 않는다.

사용: python -I DataPrep/measure_priority.py --input <경로입력> --pack <pack> --facilities <시설목록.geojson> --from <출발 시설> --out <결과.csv> [--top 15]
"""
import argparse
import collections
import contextlib
import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # python -I는 스크립트 폴더를 넣지 않는다
import route_engine as R  # noqa: E402

RANK = {"none": 0, "uncertain": 1, "ok": 2}


def measured_ok(item):
    """그 구간을 재 보니 문제없음(가정): 값·장벽·노면 기록 없이 다 잰 구간."""
    return {**item, "status": "done", "missing": [], "blocked": None, "values": [], "barriers": [], "surfaces": []}


@contextlib.contextmanager
def _cached_judge():
    """길 하나를 찾을 때마다 엔진이 모든 구간을 다시 판정하므로, 같은 (구간 기록, 유형, 범위)의 판정을 기억해 빠르게 한다.
    끝나면 엔진의 judge를 되돌린다."""
    orig, memo = R.judge, {}

    def judge(items, mode, lo=0.0, hi=None, **kw):
        key = (id(items), mode, lo, hi, tuple(sorted(kw.items())))
        if key not in memo:
            memo[key] = (items, orig(items, mode, lo, hi, **kw))  # items를 함께 잡아 둬 id가 다시 쓰이지 않게 한다
        return memo[key][1]

    R.judge = judge
    try:
        yield
    finally:
        R.judge = orig


def route_all(ctx, facs, start, modes) -> dict:
    """{(도착 이름, 유형): 결과}. 출발지 자신은 뺀다."""
    with _cached_judge():
        return {(f["name"], m): R.route_by_names(ctx, facs, start, f["name"], m)
                for m in modes for f in facs if f["name"] != start}


def used_segments(results) -> collections.Counter:
    """결과 길에서 막힘·불확실로 나온 구간과 그 구간이 나온 (도착, 유형) 수."""
    c = collections.Counter()
    for r in results.values():
        segs = {b["seg"] for b in r["blocked_by"]} | {s["seg"] for s in r["steps"] if s["state"] != "ok"}
        c.update(segs)
    return c


def gains(ctx, facs, start, modes, segs, base=None) -> dict:
    """{구간: {유형: 결과가 좋아지는 도착 수}}. 구간 하나씩 '재 보니 문제없음'으로 바꿔 다시 계산한다."""
    base = base or route_all(ctx, facs, start, modes)
    out = {}
    for k in segs:
        saved = ctx.items[k]
        ctx.items[k] = measured_ok(saved)
        try:
            new = route_all(ctx, facs, start, modes)
        finally:
            ctx.items[k] = saved
        out[k] = {m: sum(RANK[new[key]["status"]] > RANK[base[key]["status"]] for key in base if key[1] == m) for m in modes}
    return out


def reasons_of(results, k) -> dict:
    """{유형: 그 구간의 판정 이유(중복 없이 앞 3개)}."""
    out = {}
    for (_, m), r in results.items():
        for s in r["steps"]:
            if s["seg"] == k and s["state"] != "ok":
                lst = out.setdefault(m, [])
                lst += [x for x in s["reasons"] if x not in lst]
    return {m: v[:3] for m, v in out.items()}


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="실측 우선 구간")
    ap.add_argument("--input", required=True)
    ap.add_argument("--pack", required=True)
    ap.add_argument("--facilities", required=True)
    ap.add_argument("--from", dest="src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args(argv)
    ctx, facs = R.load(a.input, a.pack, a.facilities)
    modes = list(R.MODES)
    base = route_all(ctx, facs, a.src, modes)
    used = used_segments(base)
    g = gains(ctx, facs, a.src, modes, list(used), base)
    rows = sorted(g, key=lambda k: (-sum(g[k].values()), -used[k], k))
    cnt = {m: collections.Counter(base[key]["status"] for key in base if key[1] == m) for m in modes}
    print(f"{ctx.site}: {a.src}에서 {len(facs) - 1}곳(갈 수 있음/불확실/갈 수 없음) " +
          ", ".join(f"{m} {c['ok']}/{c['uncertain']}/{c['none']}" for m, c in cnt.items()) + (" (가상 자료)" if ctx.test else ""))
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["순위", "구간", "길이_m", "좋아지는_도착_합", *[f"좋아짐_{m}" for m in modes], "길에_나온_수",
                    *[f"이유_{m}" for m in modes]])
        for i, k in enumerate(rows, 1):
            rs = reasons_of(base, k)
            w.writerow([i, k, round(ctx.segs[k]["len"], 1), sum(g[k].values()), *[g[k][m] for m in modes], used[k],
                        *[" · ".join(rs.get(m, [])) for m in modes]])
            if i <= a.top:
                print(f"{i:>2}. 구간 {k} ({ctx.segs[k]['len']:.1f} m): 좋아지는 도착 " +
                      ", ".join(f"{m} {g[k][m]}" for m in modes) + " | " +
                      " / ".join(f"{m}: {' · '.join(v)}" for m, v in rs.items()))
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
