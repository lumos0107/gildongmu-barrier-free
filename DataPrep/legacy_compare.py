"""지금(legacy) 경로 엔진 결과가 바이트까지 그대로인지 확인한다(2026-11-21 가중치 경로 작업용).

    python -I DataPrep/legacy_compare.py --save   # 기준 만들기(가중치 작업 전 한 번)
    python -I DataPrep/legacy_compare.py          # 지금 코드로 다시 만들어 기준과 비교

두 대상지 정문에서 모든 시설 × 세 유형의 route_by_names 결과, CLI 한 번의 결과 파일과 화면 글,
실측 우선 도구(measure_priority.py)의 CSV와 화면 글을 비교한다. 인자 없이 쓰는 지금 동작만 본다.
"""
import argparse
import contextlib
import io
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import measure_priority as MP  # noqa: E402
import route_engine as R  # noqa: E402

D = pathlib.Path(r"C:\Users\seungjun\Documents\work\베리어프리\공통자료\10_관광지지도")
SITES = {
    "minsokchon": (HERE / "out/경로입력_가상.json", D / "측정앱자료/minsokchon_c5ad2ca2ed6f.json",
                   D / "minsokchon/시설목록.geojson", "정문", "화장실 3(한복체험장 옆)"),
    "jejunu1000": (HERE / "jejunu/out/경로입력_가상.json", D / "측정앱자료/jejunu1000_9fe6fdc97b8d.json",
                   D / "jejunu1000/시설목록.geojson", "제주대학교정문", "자연과학대학"),
}
OUT = HERE / "out/가중치"


class _Buf(io.StringIO):
    def reconfigure(self, **kw):  # 엔진 main이 stdout.reconfigure를 부름
        pass


def make(dst: pathlib.Path):
    dst.mkdir(parents=True, exist_ok=True)
    for site, (ri, pack, fac, start, one) in SITES.items():
        ctx, facs = R.load(ri, pack, fac)
        allr = {f"{f['name']}|{m}": R.route_by_names(ctx, facs, start, f["name"], m)
                for m in R.MODES for f in facs if f["name"] != start}
        (dst / f"{site}.json").write_text(json.dumps(allr, ensure_ascii=False, indent=1), encoding="utf-8")
        buf = _Buf()
        with contextlib.redirect_stdout(buf):
            R.main(["--input", str(ri), "--pack", str(pack), "--facilities", str(fac), "--from", start, "--to", one,
                    "--mode", "manual", "--out", str(dst / f"cli_{site}.json")])
        (dst / f"cli_{site}.txt").write_text(buf.getvalue().replace(str(dst), "<dst>"), encoding="utf-8")
        buf = _Buf()
        with contextlib.redirect_stdout(buf):
            MP.main(["--input", str(ri), "--pack", str(pack), "--facilities", str(fac), "--from", start,
                     "--out", str(dst / f"priority_{site}.csv")])
        (dst / f"priority_{site}.txt").write_text(buf.getvalue().replace(str(dst), "<dst>"), encoding="utf-8")


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args(argv)
    base = OUT / "기준_legacy"
    if a.save:
        make(base)
        print(f"기준 저장: {base}")
        return 0
    now = OUT / "지금_legacy"
    make(now)
    bad = [p.name for p in sorted(base.iterdir()) if p.read_bytes() != (now / p.name).read_bytes()]
    print(f"비교 {len(list(base.iterdir()))}개 파일: " + ("모두 같음" if not bad else "다름 " + ", ".join(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
