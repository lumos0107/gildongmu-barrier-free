"""세 길 기준 저장·비교(B단계 Task 1, 2026-11-22). 두 대상지 정문에서 모든 곳 × 세 유형의 세 길 결과(기본 가중치,
시설 판정 켬 = 앱과 같음)와 앱 껍데기에 든 미리 계산한 길(routes)을 기준으로 두고, 코드를 바꾼 뒤 그대로인지 본다.
legacy_compare.py(예전 방식 결과)는 세 길과 앱을 보지 않아 따로 둔다.

    python -I DataPrep/three_compare.py --save [--force]   # 기준 저장(이미 있으면 멈춤)
    python -I DataPrep/three_compare.py                    # 다시 만들어 비교(다르면 종료 코드 1)
"""
import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import route_cost as RC  # noqa: E402
import route_engine as R  # noqa: E402
from legacy_compare import SITES  # noqa: E402

OUT = HERE / "out/가중치/기준_세길"
APP_DIR = pathlib.Path(r"C:\Users\seungjun\Documents\work\베리어프리\캡스톤2\14_앱껍데기")
APP = {"minsokchon": APP_DIR / "길동무_앱껍데기.html", "jejunu1000": APP_DIR / "길동무_앱껍데기_제주대.html"}


def load_site(site: str):
    """앱(build_shell)과 같게 시설 판정을 켜고 불러온다 → (ctx, facs, 출발 이름)."""
    ri, pack, fac, start, _ = SITES[site]
    ctx, facs = R.load(ri, pack, fac, facility_rules=True)
    return ctx, facs, start


def three_all(site: str) -> dict:
    ctx, facs, start = load_site(site)
    w = RC.load_weights(HERE / "route_weights.json")
    return {f"{f['name']}|{m}": R.route3_by_names(ctx, facs, start, f["name"], m, w)
            for f in facs if f["name"] != start for m in R.MODES}


def html_routes(path) -> dict:
    """앱 HTML의 `const D = {…}`를 읽어 routes만(뒤에 다른 코드가 이어져도 됨)."""
    t = pathlib.Path(path).read_text(encoding="utf-8")
    i = t.index("const D = ") + len("const D = ")
    obj, _ = json.JSONDecoder().raw_decode(t, i)
    return obj["routes"]


def _dump(x) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=True)


def diff_keys(a: dict, b: dict) -> list:
    return sorted(k for k in set(a) | set(b) if k not in a or k not in b or _dump(a[k]) != _dump(b[k]))


def save_json(path, obj, force=False):
    path = pathlib.Path(path)
    if path.exists() and not force:
        raise FileExistsError(f"기준이 이미 있음(덮으려면 --force): {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    bad = 0
    for site in SITES:
        now = {"three": three_all(site), "app": html_routes(APP[site])}
        for kind, obj in now.items():
            p = OUT / (f"{site}.json" if kind == "three" else f"앱_{site}_routes.json")
            if a.save:
                save_json(p, obj, force=a.force)
                print(f"저장: {p.name} ({len(obj)}쌍)")
                continue
            ref = json.loads(p.read_text(encoding="utf-8"))
            d = diff_keys(ref, json.loads(json.dumps(obj, ensure_ascii=False)))
            bad += len(d)
            print(f"{p.name}: {'같음' if not d else f'다름 {len(d)}쌍, 예: {d[:3]}'}")
    if not a.save:
        print("모두 같음" if not bad else f"다름 {bad}쌍")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
