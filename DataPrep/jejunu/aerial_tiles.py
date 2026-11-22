"""항공사진 보행로 그리기용 조각 그림(설계 6장 나 5), 계획 Task 5).

사용: python -I DataPrep/jejunu/aerial_tiles.py [--tile 150] [--only-gaps]
결과: out/조각/<행>_<열>.jpg. 19단계 항공사진(aerial_z19_full.jpg) 화소 좌표 눈금(10 m = 약 40 화소),
연결망(큰 조각 = 흰색, 떨어진 조각 = 주황), 계단(파랑), 이어지지 않은 계단 끝(빨간 원).
traced_paths.json의 px는 이 그림의 눈금 숫자(전체 사진 화소)로 적는다.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from PIL import Image, ImageDraw  # noqa: E402

import common  # noqa: E402
import net_graph as NG  # noqa: E402

Image.MAX_IMAGE_PIXELS = None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tile", type=float, default=150.0)
    ap.add_argument("--only-gaps", action="store_true")
    ap.add_argument("--drawn", action="store_true", help="그린 길이 있는 조각도 뽑는다")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    g = common.load_geo("aerial_z19_full.json")
    im = Image.open(common.SITE_DIR / "aerial_z19_full.jpg").convert("RGB")
    parts = NG.load_parts(common.SITE_DIR / "network.geojson")
    # 조각 표시
    key = lambda c: (round(c[0], 2), round(c[1], 2))  # noqa: E731
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for p in parts:
        parent[find(key(p["geom"].coords[0]))] = find(key(p["geom"].coords[-1]))
    size = {}
    for p in parts:
        r = find(key(p["geom"].coords[0]))
        size[r] = size.get(r, 0) + p["geom"].length
    main_r = max(size, key=size.get)
    d = ImageDraw.Draw(im)
    for p in parts:
        px = [g.px_from5186(*c) for c in p["geom"].coords]
        if p["props"].get("highway") == "steps":
            col, w = (0, 140, 255), 5
        elif p["props"].get("kind") == "drawn":
            col, w = (0, 255, 255), 3
        else:
            col, w = ((255, 255, 255), 2) if find(key(p["geom"].coords[0])) == main_r else ((255, 140, 0), 3)
        d.line(px, fill=col, width=w)
    st = json.loads((common.OUT / "계단_연결.json").read_text(encoding="utf-8"))
    gaps = []
    for s in st["loose"]:
        for c, ok in zip(s["ends"], s["ok"]):
            if not ok:
                x, y = g.px_from5186(*c)
                gaps.append((x, y))
                d.ellipse([x - 9, y - 9, x + 9, y + 9], outline=(255, 0, 0), width=3)
    drawn = [g.px_from5186(*q) for p in parts if p["props"].get("kind") == "drawn" for q in p["geom"].coords]
    T = int(a.tile / g.mpp)
    outd = common.OUT / "조각"
    outd.mkdir(parents=True, exist_ok=True)
    for f in outd.glob("*.jpg"):
        f.unlink()
    n = 0
    for r in range(0, im.height, T):
        for c in range(0, im.width, T):
            want = any(c <= x < c + T and r <= y < r + T for x, y in gaps)
            if a.drawn:
                want = want or any(c <= x < c + T and r <= y < r + T for x, y in drawn)
            if (a.only_gaps or a.drawn) and not want:
                continue
            tile = im.crop((c, r, min(c + T, im.width), min(r + T, im.height))).copy()
            td = ImageDraw.Draw(tile)
            step = 40
            for k in range(0, T + 1, step):
                td.line([(k, 0), (k, 6 if k % 80 else 14)], fill=(255, 255, 0), width=1)
                td.line([(0, k), (6 if k % 80 else 14, k)], fill=(255, 255, 0), width=1)
                if k % 80 == 0:
                    td.text((k + 2, 14), str(c + k), fill=(255, 255, 0))
                    td.text((16, k + 2), str(r + k), fill=(255, 255, 0))
            tile.save(outd / f"{r // T:02d}_{c // T:02d}.jpg", quality=88)
            n += 1
    print(f"조각 {n}장, 이어지지 않은 계단 끝 {len(gaps)}개, 조각 크기 {T} 화소 -> {outd}")


if __name__ == "__main__":
    main()
