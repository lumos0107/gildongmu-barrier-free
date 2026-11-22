"""이어지지 않은 계단 끝에서 기존 길까지, 항공사진 위 가장 싼 길을 찾아 traced_paths.json에 넣는다(설계 7장 나 '반자동').

값: 포장·맨땅 1, 잔디 6, 나무 25, 건물·다른 계단 면은 못 지남. 18단계 사진(0.5 m/화소)에서 찾고 19단계 화소로 적는다.
한 끝에서 70 m 안에 길이 없거나, 지나는 길의 절반 넘게 나무면 넣지 않고 manual 목록에 남긴다(조각 그림으로 확인).
손으로 고친 선(auto가 아닌 것)은 그대로 둔다.

사용: python -I DataPrep/jejunu/trace_auto.py   (build_net.py를 traced 없이 한 번 돌린 뒤)
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from scipy.sparse import coo_matrix  # noqa: E402
from scipy.sparse.csgraph import dijkstra  # noqa: E402
from shapely.geometry import LineString, Point  # noqa: E402

import common  # noqa: E402
import net_graph as NG  # noqa: E402
from common import OUT, SITE_DIR, campus_zone, load_1000, new_buildings, shape_of  # noqa: E402

TRACED = pathlib.Path(__file__).resolve().parent / "traced_paths.json"
COMPONENTS = "--components" in sys.argv
R_M = 70.0
TREE_MAX = 0.25  # 지나는 길에서 나무(어두운 초록) 화소 비율 상한


def cost_map(img):
    a = img.astype(float)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    lum = a.mean(-1)
    gd = g - np.maximum(r, b)
    c = np.ones(lum.shape)
    c[gd > 5] = 6.0
    c[(gd > 5) & (lum < 95)] = 25.0
    return c


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    geo = common.load_geo()  # 18단계 0.5 m/화소
    img = np.asarray(Image.open(SITE_DIR / "aerial_z19.jpg").convert("RGB"))
    H, W = img.shape[:2]
    cost = cost_map(img)
    feats = load_1000()
    zone = campus_zone()
    block = Image.new("L", (W, H), 0)
    bd = ImageDraw.Draw(block)
    polys = [shape_of(f) for f in feats if f["code"] == "B0010000" and f["gtype"] == "A"] + new_buildings(feats, campus_zone(0))
    for p in polys:
        for q in ([p] if p.geom_type == "Polygon" else list(p.geoms)):
            bd.polygon([geo.px_from5186(*c) for c in q.exterior.coords], fill=1)
    stair_polys = [shape_of(f) for f in feats if f["code"] == "C0390000" and f["gtype"] == "A"]
    # 옹벽·석축(0.5 m 넘는 것)도 못 지나간다: 그린 길이 벽을 넘으면 땅 높이 끊김을 밟아 말이 안 되는 경사가 생긴다
    for f in feats:
        if f["code"] == "F0040000" and f["gtype"] == "L" and common.attr_float(f, "높이") > 0.5:
            bd.line([geo.px_from5186(*c) for c in f["geom"][0]], fill=1, width=3)
    parts = NG.load_parts(SITE_DIR / "network.geojson")
    target = Image.new("L", (W, H), 0)
    td = ImageDraw.Draw(target)
    for p in parts:
        if p["props"].get("highway") != "steps":
            td.line([geo.px_from5186(*c) for c in p["geom"].coords], fill=1, width=2)
    block, target = np.asarray(block) > 0, np.asarray(target) > 0
    st = json.loads((OUT / "계단_연결.json").read_text(encoding="utf-8"))
    data = json.loads(TRACED.read_text(encoding="utf-8"))
    keep = [p for p in data["paths"] if not p.get("auto")] if not COMPONENTS else data["paths"]
    nid = max([p["id"] for p in keep], default=0) + 1
    manual, added = [], 0
    rpx = int(R_M / geo.mpp)

    def route(c, T_full):
        """5186 점 c에서 T_full(화소 표시) 가운데 가장 싼 곳까지. (19단계 화소 평탄 목록, 나무 비율) 또는 (None, 이유)."""
        x0, y0 = geo.px_from5186(*c)
        cx, cy = int(round(x0)), int(round(y0))
        if not (0 <= cx < W and 0 <= cy < H):
            return None, "사진 밖"
        xa, xb, ya, yb = max(0, cx - rpx), min(W, cx + rpx + 1), max(0, cy - rpx), min(H, cy + rpx + 1)
        C = cost[ya:yb, xa:xb]
        sb = Image.new("L", (xb - xa, yb - ya), 0)
        sd = ImageDraw.Draw(sb)
        e = Point(c)
        for sp in stair_polys:
            if sp.distance(e) < R_M:
                for q in ([sp] if sp.geom_type == "Polygon" else list(sp.geoms)):
                    sd.polygon([(geo.px_from5186(*v)[0] - xa, geo.px_from5186(*v)[1] - ya) for v in q.exterior.coords], fill=1)
        yy, xx = np.mgrid[ya:yb, xa:xb]
        near = (xx - x0) ** 2 + (yy - y0) ** 2 <= (2.0 / geo.mpp) ** 2
        B = (block[ya:yb, xa:xb] | (np.asarray(sb) > 0)) & ~near
        T = T_full[ya:yb, xa:xb] & ~near
        h, w = C.shape
        idx = np.arange(h * w).reshape(h, w)
        rows, cols, wts = [], [], []
        Bf, Cf = B.ravel(), C.ravel()
        for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
            a = idx[0:h - dy, max(0, -dx):w - max(0, dx)].ravel()
            b = idx[dy:h, max(0, dx):w - max(0, -dx)].ravel()
            ok_ = ~(Bf[a] | Bf[b])
            rows.append(a[ok_]), cols.append(b[ok_]), wts.append(((Cf[a] + Cf[b]) / 2 * np.hypot(dx, dy))[ok_])
        G = coo_matrix((np.concatenate(wts), (np.concatenate(rows), np.concatenate(cols))), shape=(h * w, h * w)).tocsr()
        src = idx[cy - ya, cx - xa]
        dist, pred = dijkstra(G, directed=False, indices=src, return_predecessors=True)
        tgt = np.where(T.ravel() & np.isfinite(dist))[0]
        if not len(tgt):
            return None, f"{R_M:g} m 안에 이을 길 없음"
        t = tgt[np.argmin(dist[tgt])]
        path = [t]
        while path[-1] != src and pred[path[-1]] >= 0:
            path.append(pred[path[-1]])
        pys, pxs = np.divmod(np.array(path[::-1]), w)
        share = float((C[pys, pxs] >= 25).mean())
        if share > TREE_MAX:
            return None, f"지나는 길 나무 {share:.0%}"
        ln = LineString([(x0, y0)] + [(px + xa, py + ya) for px, py in zip(pxs, pys)]).simplify(2.0)
        if ln.length < 2:
            return None, "너무 짧음"
        return [round(v * 2, 1) for xy in ln.coords for v in xy], share

    if not COMPONENTS:
        for s in st["loose"]:
            for c, ok in zip(s["ends"], s["ok"]):
                if ok:
                    continue
                flat, share = route(c, target)
                if flat is None:
                    manual.append({"osm": s["osm"], "end": c, "why": share})
                    continue
                keep.append({"id": nid, "px": flat, "src": "항공사진", "auto": "stair", "w": 1.5, "note": f"자동: 계단 {s['osm']} 끝, 나무 {share:.0%}"})
                nid += 1
                added += 1
    else:
        keep = list(data["paths"])  # 앞선 잇기는 남기고 아직 떨어진 조각만 더한다
        nid = max([p["id"] for p in keep], default=0) + 1
        key = lambda c: (round(c[0], 2), round(c[1], 2))  # noqa: E731
        par = {}

        def find(x):
            par.setdefault(x, x)
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x
        for p in parts:
            par[find(key(p["geom"].coords[0]))] = find(key(p["geom"].coords[-1]))
        size = {}
        for p in parts:
            r = find(key(p["geom"].coords[0]))
            size[r] = size.get(r, 0) + p["geom"].length
        main_r = max(size, key=size.get)
        mm = Image.new("L", (W, H), 0)
        md = ImageDraw.Draw(mm)
        main_u = []
        for p in parts:
            if find(key(p["geom"].coords[0])) == main_r and p["props"].get("highway") != "steps":
                md.line([geo.px_from5186(*c) for c in p["geom"].coords], fill=1, width=2)
                main_u.append(p["geom"])
        from shapely.ops import unary_union
        main_u = unary_union(main_u)
        mmask = np.asarray(mm) > 0
        for r in size:
            if r == main_r:
                continue
            pts = [Point(c) for p in parts if find(key(p["geom"].coords[0])) == r for c in p["geom"].coords]
            pts = sorted(pts, key=main_u.distance)[:3]
            best = None
            for q in pts:
                flat, share = route((q.x, q.y), mmask)
                if flat is not None:
                    L = LineString([(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]).length
                    if best is None or L < best[0]:
                        best = (L, flat, share)
            if best is None:
                manual.append({"component_m": round(size[r]), "at": [pts[0].x, pts[0].y], "why": "큰 조각까지 길 못 찾음"})
                continue
            keep.append({"id": nid, "px": best[1], "src": "항공사진", "auto": "comp", "w": 1.5, "note": f"자동: 떨어진 조각 {round(size[r])} m 잇기, 나무 {best[2]:.0%}"})
            nid += 1
            added += 1
    data["paths"] = keep
    data["manual" if not COMPONENTS else "manual_components"] = manual
    TRACED.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"자동 경로 {added}개, 손으로 볼 끝 {len(manual)}개 -> {TRACED}")


if __name__ == "__main__":
    main()
