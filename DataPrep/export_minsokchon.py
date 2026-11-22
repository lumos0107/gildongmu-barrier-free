"""제주민속촌 자료를 Unity용 JSON 하나와 항공사진으로 바꾼다.

좌표: 항공사진(2560 px, 19단계) 가운데가 원점, x = 동쪽 m, z = 북쪽 m.
- 길: 측정앱 묶음(pack)의 구간을 그대로 쓴다(구간 번호가 측정 앱·route input과 같다). 사진 밖으로 나가는 구간은 뺀다.
- 계단: network.geojson의 cls=steps
- 건물: 영역 안은 OSM 건물 + OSM에 없는 브이월드 건물, 영역 밖은 브이월드 건물(make_3d.py와 같은 규칙)
  종류: OSM roof:material=thatch는 초가. 나머지는 항공사진 지붕 색으로 초가(황토색)·기와(어두운 회색)·현대로 가른다.
- 나무: 항공사진에서 어두운 초록(숲)을 뽑아 4.5 m 간격으로 심는다. 길·건물 자리는 비운다.

사용: python -I export_minsokchon.py <장소 폴더> <측정앱 pack.json> <출력 폴더>
"""
import json, math, pathlib, random, shutil, sys

import cv2
import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")
D, PACK, OUT = (pathlib.Path(a) for a in sys.argv[1:4])
OUT.mkdir(parents=True, exist_ok=True)
rd = lambda p: json.loads(p.read_text(encoding="utf-8"))

meta = rd(D / "aerial_z19.json")
pack = rd(PACK)
W, H = meta["size_px"]
OX, OY = meta["tile_origin_px"]
Z, MPP = meta["zoom"], meta["m_per_px"]
assert pack["map"]["origin"] == [OX, OY] and pack["map"]["zoom"] == Z, "pack과 항공사진 기준이 다름"


def px(lon, lat):
    n = 256 * 2 ** Z
    s = math.sin(math.radians(lat))
    return (lon + 180) / 360 * n - OX, (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n - OY


def loc(x, y):  # 사진 픽셀 -> (동 m, 북 m)
    return round((x - W / 2) * MPP, 2), round((H / 2 - y) * MPP, 2)


def flat(pts):
    return [v for p in pts for v in p]


def inside(x, y, ring):
    c = False
    for i in range(len(ring)):
        (x1, y1), (x2, y2) = ring[i], ring[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def area2(ring):
    return sum(ring[i - 1][0] * ring[i][1] - ring[i][0] * ring[i - 1][1] for i in range(len(ring)))


def ear_clip(ring):
    """반시계 방향 단순 다각형을 삼각형 번호 목록으로."""
    idx = list(range(len(ring)))
    tris = []

    def convex(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) > 1e-9

    def in_tri(p, a, b, c):
        d1 = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        d2 = (c[0] - b[0]) * (p[1] - b[1]) - (c[1] - b[1]) * (p[0] - b[0])
        d3 = (a[0] - c[0]) * (p[1] - c[1]) - (a[1] - c[1]) * (p[0] - c[0])
        return d1 >= 0 and d2 >= 0 and d3 >= 0

    guard = 0
    while len(idx) > 3 and guard < 5000:
        guard += 1
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = ring[i0], ring[i1], ring[i2]
            if not convex(a, b, c):
                continue
            if any(in_tri(ring[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            tris += [i0, i1, i2]
            idx.pop(k)
            break
        else:
            break  # 귀를 못 찾음: 남은 것은 부채꼴로
    for k in range(1, len(idx) - 1):
        tris += [idx[0], idx[k], idx[k + 1]]
    return tris


# 영역 -------------------------------------------------------------------------
site_ll = rd(D / "osm_site.geojson")["features"][0]["geometry"]["coordinates"][0]
site_px = [px(*p) for p in site_ll]
in_site_px = lambda ring_px: inside(sum(p[0] for p in ring_px) / len(ring_px), sum(p[1] for p in ring_px) / len(ring_px), site_px)

# 길 ---------------------------------------------------------------------------
segs, dropped = [], 0
for s in pack["segs"]:
    xy = list(zip(s["xy"][0::2], s["xy"][1::2]))
    if not all(0 <= x <= W and 0 <= y <= H for x, y in xy):
        dropped += 1
        continue
    w = 5.0 if s["road"] else (1.8 if s["drawn"] else 2.2)
    segs.append({"id": s["seg"], "a": s["a"], "b": s["b"], "road": s["road"], "drawn": s["drawn"] > 0, "len": s["len"],
                 "inc": s["inclines"], "w": w, "p": flat(loc(x, y) for x, y in xy), "_px": xy})

net = rd(D / "network.geojson")
steps = []
for f in net["features"]:
    if f["properties"]["cls"] == "steps":
        steps.append({"p": flat(loc(*px(*q)) for q in f["geometry"]["coordinates"])})

# 건물 -------------------------------------------------------------------------
img = np.array(Image.open(D / "aerial_z19.jpg").convert("RGB")).astype(np.float32)
bmask = np.zeros((H, W), np.uint8)


def roof_color(ring_px):
    m = np.zeros((H, W), np.uint8)
    cv2.fillPoly(m, [np.array(ring_px, np.int32)], 1)
    m = cv2.erode(m, np.ones((3, 3), np.uint8))
    sel = img[m > 0]
    if not len(sel):
        sel = img[int(ring_px[0][1]) % H, int(ring_px[0][0]) % W][None]
    # 빨강·초록 칠 지붕(현대 건물) 픽셀 비율: 여러 색이 섞이면 평균색이 흐려져서 따로 센다
    painted = ((sel[:, 0] - sel[:, 1] > 18) | ((sel[:, 1] - sel[:, 0] > 25) & (sel.mean(1) > 90))).mean()
    return sel.mean(0), painted


osm = rd(D / "osm_features.geojson")
vwb = rd(D / "vw_buildings.geojson")
vw = []
for f in vwb["features"]:
    g = f["geometry"]
    for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
        vp = f["properties"]
        vw.append({"ring": [px(*q) for q in poly[0]], "floors": int(vp.get("gro_flo_co") or 0), "name": vp.get("buld_nm") or ""})

raw = []  # (ring_px, floors, name, thatch_tag, in_site)
osm_in = []
for f in osm["features"]:
    p = f["properties"]
    if "building" not in p or f["geometry"]["type"] != "Polygon":
        continue
    ring = [px(*q) for q in f["geometry"]["coordinates"][0]]
    if not in_site_px(ring):
        continue
    osm_in.append(ring)
    hits = [v["floors"] for v in vw if inside(*np.mean(v["ring"], 0), ring)]
    raw.append((ring, int(p.get("building:levels") or 0) or (max(hits) if hits else 1), p.get("name", ""), p.get("roof:material") == "thatch", True))
for v in vw:
    ins = in_site_px(v["ring"])
    if ins and any(inside(*np.mean(v["ring"], 0), r) for r in osm_in):
        continue
    raw.append((v["ring"], v["floors"], v["name"], False, ins))

seg_pts = np.array([loc(x, y) for s in segs for x, y in s["_px"]])
buildings, kinds = [], {"thatch": 0, "tile": 0, "modern": 0}
for ring_px, floors, name, thatch_tag, ins in raw:
    if ring_px[0] == ring_px[-1]:
        ring_px = ring_px[:-1]
    if len(ring_px) < 3:
        continue
    cv2.fillPoly(bmask, [np.array(ring_px, np.int32)], 1)
    col, painted = roof_color(ring_px)
    r, g, b = col
    area = abs(area2([loc(x, y) for x, y in ring_px])) / 2
    lum, rb, sat = col.mean(), r - b, (col.max() - col.min()) / max(col.max(), 1)
    floors = max(floors, 1)
    # 기와 = 어두운 푸른 회색(파랑 >= 빨강 + 3). 나무에 덮인 초가는 빨강 = 파랑 정도라 초가로 둔다.
    if thatch_tag:
        kind = "thatch"
    elif ins and floors <= 2 and lum < 100 and b - r >= 3:
        kind = "tile"
    elif ins and floors <= 2 and sat < 0.2 and rb >= -2 and painted < 0.15 and area <= 160:
        kind = "thatch"
    else:
        kind = "modern"
    kinds[kind] += 1
    ring = [loc(x, y) for x, y in ring_px]
    if area2(ring) < 0:
        ring = ring[::-1]
    (cx, cz), (bw, bd), _ = cv2.minAreaRect(np.array(ring, np.float32))
    box = cv2.boxPoints(((cx, cz), (bw, bd), _))
    e1, e2 = box[1] - box[0], box[2] - box[1]
    long_e = e1 if np.linalg.norm(e1) >= np.linalg.norm(e2) else e2
    ang = math.degrees(math.atan2(long_e[1], long_e[0]))
    w, d = max(bw, bd), min(bw, bd)
    # 앞면: 가장 가까운 길 쪽 긴 면(초가·기와의 문을 그쪽에 단다)
    near = seg_pts[np.argmin(((seg_pts - [cx, cz]) ** 2).sum(1))] if len(seg_pts) else np.array([cx, cz + 1])
    n = np.array([-math.sin(math.radians(ang)), math.cos(math.radians(ang))])
    front = 1 if np.dot(near - [cx, cz], n) >= 0 else -1
    item = {"kind": kind, "name": name, "floors": floors, "inSite": ins, "cx": round(float(cx), 2), "cz": round(float(cz), 2),
            "w": round(float(w), 2), "d": round(float(d), 2), "ang": round(ang, 1), "front": front,
            "roof": [round(float(c) / 255, 3) for c in col], "ring": flat(ring), "tris": ear_clip(ring)}
    buildings.append(item)

# 나무 -------------------------------------------------------------------------
blur = cv2.GaussianBlur(img, (0, 0), 1.5)
r, g, b = blur[..., 0], blur[..., 1], blur[..., 2]
lum = (r + g + b) / 3
tree = ((g - r > 10) & (g >= b) & (lum < 78)).astype(np.uint8)
tree = cv2.morphologyEx(tree, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
tree = cv2.morphologyEx(tree, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
keep_out = cv2.dilate(bmask, np.ones((9, 9), np.uint8))
for s in segs:
    half_px = int((s["w"] / 2 + 1.2) / MPP)
    cv2.polylines(keep_out, [np.array(s["_px"], np.int32)], False, 1, thickness=2 * half_px + 1)
tree[keep_out > 0] = 0
dist = cv2.distanceTransform(tree, cv2.DIST_L2, 5)
rng = random.Random(7)
step = 4.5 / MPP
trees = []
y = step / 2
while y < H:
    x = step / 2
    while x < W:
        tx, ty = int(x + rng.uniform(-0.35, 0.35) * step), int(y + rng.uniform(-0.35, 0.35) * step)
        if 0 <= tx < W and 0 <= ty < H and tree[ty, tx]:
            rad = min(3.6, max(1.5, dist[ty, tx] * MPP + 1.2)) * rng.uniform(0.85, 1.15)
            l = lum[ty, tx]
            shade = 0 if l < 58 else (1 if l < 68 else 2)
            trees += [*loc(tx, ty), round(float(rad), 2), shade]
        x += step
    y += step

# 내보내기 ---------------------------------------------------------------------
for s in segs:
    del s["_px"]
sx, sy = pack["start"]
out = {
    "site": "minsokchon", "name": "제주민속촌", "pack": pack.get("hash"), "net": pack.get("net"),
    "mpp": MPP, "sizeM": round(W * MPP, 2), "start": list(loc(sx, sy)), "startNode": pack["start_node"],
    "boundary": flat(loc(x, y) for x, y in site_px),
    "segs": segs, "steps": steps, "buildings": buildings, "trees": trees,
}
(OUT / "minsokchon_map.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
shutil.copyfile(D / "aerial_z19.jpg", OUT / "aerial.jpg")
print(f"길 {len(segs)}구간(사진 밖 {dropped} 뺌), 계단 {len(steps)}줄, 건물 {len(buildings)}동 {kinds}, 나무 {len(trees) // 4}그루")
