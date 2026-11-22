"""제주대 3D 맵 공통: 경로, 좌표 변환, 공개 지도 읽기.

설계: Docs/2026-11-15-제주대맵-설계.md, 계획: Docs/2026-11-15-제주대맵-작업계획.md
좌표계: 1:1,000 = EPSG:5186, 1:5,000 = EPSG:5179, Unity = 항공사진 가운데 원점(x 동쪽 m, z 북쪽 m).
"""
import csv
import glob
import json
import math
import os
import pathlib
import re
import sys

import shapefile
from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon, shape
from shapely.ops import unary_union

HERE = pathlib.Path(__file__).resolve().parent
for _p in (HERE, HERE.parent):  # python -I는 스크립트 폴더를 자동으로 넣지 않는다
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

BF = pathlib.Path(r"C:\Users\seungjun\Documents\work\베리어프리")
DATA = BF / "공통자료" / "10_관광지지도"
SITE = "jejunu1000"
SITE_DIR = DATA / SITE
SRC_DIR = DATA / "jejunu"
MAP1000 = SRC_DIR / "온라인자료" / "수치지형도_1000_20도엽"
MAP5000 = pathlib.Path(r"C:\Users\seungjun\Documents\work\논문\정보기술학회\데이터\원본\국토정보맵\연속수치지도_제주_20261109\풀기")
EVENING = BF / "Barrier-free-information-gathering-app" / "tools"
PACK_DIR = DATA / "측정앱자료"
OUT = HERE / "out"

_T4326_5186 = Transformer.from_crs(4326, 5186, always_xy=True)
_T5186_4326 = Transformer.from_crs(5186, 4326, always_xy=True)
_T5179_5186 = Transformer.from_crs(5179, 5186, always_xy=True)


class Geo:
    """항공사진 메타(aerial_z19*.json) 하나에 묶인 좌표 변환."""

    def __init__(self, meta: dict):
        self.meta = meta
        self.zoom = meta["zoom"]
        self.ox, self.oy = meta["tile_origin_px"]
        self.W, self.H = meta["size_px"]
        self.mpp = meta["m_per_px"]
        self.size_m = self.W * self.mpp
        self.n = 256 * 2 ** self.zoom

    def px(self, lon, lat):
        s = math.sin(math.radians(lat))
        return (lon + 180) / 360 * self.n - self.ox, (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * self.n - self.oy

    def lonlat(self, x, y):
        gx, gy = self.ox + x, self.oy + y
        return gx / self.n * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * gy / self.n))))

    @staticmethod
    def to5186(lon, lat):
        return _T4326_5186.transform(lon, lat)

    @staticmethod
    def from5186(x, y):
        return _T5186_4326.transform(x, y)

    def unity(self, x, y):
        return (x - self.W / 2) * self.mpp, (self.H / 2 - y) * self.mpp

    def unity_inv(self, ux, uz):
        return ux / self.mpp + self.W / 2, self.H / 2 - uz / self.mpp

    def unity_from5186(self, x, y):
        return self.unity(*self.px(*self.from5186(x, y)))

    def px_from5186(self, x, y):
        return self.px(*self.from5186(x, y))

    def from_unity(self, ux, uz):
        return self.to5186(*self.lonlat(*self.unity_inv(ux, uz)))


def load_geo(name="aerial_z19.json") -> Geo:
    return Geo(json.loads((SITE_DIR / name).read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# 1:1,000 수치지형도 Ver2.0 (2025 SHP 5장 + 2011·2013 NGI 15장)
# ---------------------------------------------------------------------------
def _shp_geom(s, gt):
    pts = s.points
    parts = list(s.parts) + [len(pts)]
    if gt == "P":
        return [tuple(pts[0])] if pts else []
    return [[tuple(p) for p in pts[parts[i]:parts[i + 1]]] for i in range(len(parts) - 1)]


def _blocks(text):
    o = {}
    for p in re.split(r"<LAYER_START>", text)[1:]:
        m = re.search(r'\$LAYER_NAME\s*"([^"]+)"', p)
        if m:
            o[m.group(1)] = p
    return o


def load_1000(root=MAP1000) -> list:
    root = pathlib.Path(root)
    feats = []
    for d in sorted(glob.glob(str(root / "풀기" / "*"))):
        sheet = os.path.basename(d)
        for f in sorted(glob.glob(os.path.join(d, "*.shp"))):
            m = re.match(r"N1([PLA])_(\w+)\.shp", os.path.basename(f))
            gt, code = m.group(1), m.group(2)
            r = shapefile.Reader(f, encoding="cp949", encodingErrors="replace")
            names = [x[0] for x in r.fields[1:]]
            for sr in r.iterShapeRecords():
                feats.append({"code": code, "gtype": gt, "geom": _shp_geom(sr.shape, gt),
                              "attrs": dict(zip(names, [str(v) for v in sr.record])), "sheet": sheet, "src": "1:1000(2025)"})
            r.close()
    for f in sorted(glob.glob(str(root / "원본" / "*.ngi"))):
        mm = re.search(r"수치지도_(\d+)_(\d{4})", os.path.basename(f))
        sh, yr = mm.group(1), mm.group(2)
        t = open(f, "rb").read().decode("cp949", "replace")
        n = open(f[:-4] + ".nda", "rb").read().decode("cp949", "replace")
        gb, ab = _blocks(t), _blocks(n)
        for layer, body in gb.items():
            attrs = {}
            if layer in ab and "<DATA>" in ab[layer]:
                fields = re.findall(r'ATTRIB\("([^"]+)"', ab[layer])
                for i, row in re.findall(r"\$RECORD\s+(\d+)\s*\r?\n([^\r\n]*)", ab[layer].split("<DATA>")[1]):
                    vals = next(csv.reader([row], skipinitialspace=True))
                    attrs[int(i)] = dict(zip(fields, vals))
            data = body.split("<DATA>")[1] if "<DATA>" in body else ""
            for rec in re.split(r"\$RECORD\s+", data)[1:]:
                lines = [x.strip() for x in rec.strip().splitlines()]
                rid, typ = int(lines[0]), lines[1]
                if typ == "POINT":
                    geom, gt = [tuple(map(float, lines[2].split()[:2]))], "P"
                elif typ.startswith("TEXT"):
                    geom, gt = [tuple(map(float, lines[2].split()[:2]))], "T"
                elif typ == "LINESTRING":
                    k = int(lines[2])
                    geom, gt = [[tuple(map(float, lines[3 + j].split()[:2])) for j in range(k)]], "L"
                elif typ == "POLYGON":
                    npart, pos, geom = int(lines[2].split()[1]), 3, []
                    for _ in range(npart):
                        k = int(lines[pos]); pos += 1
                        geom.append([tuple(map(float, lines[pos + j].split()[:2])) for j in range(k)]); pos += k
                    gt = "A"
                else:
                    continue
                feats.append({"code": layer, "gtype": gt, "geom": geom, "attrs": attrs.get(rid, {}), "sheet": sh, "src": f"1:1000({yr})"})
    return feats


def shape_of(f):
    """기록 하나를 shapely 도형으로(좌표는 기록 그대로)."""
    g, gt = f["geom"], f["gtype"]
    if gt in "PT":
        return Point(g[0])
    if gt == "L":
        return LineString(g[0]) if len(g[0]) > 1 else Point(g[0][0])
    if len(g[0]) < 3:
        return Point(g[0][0])
    p = Polygon(g[0], [r for r in g[1:] if len(r) > 2])
    return p if p.is_valid else p.buffer(0)


def attr_float(f, key, default=0.0):
    try:
        return float(str(f["attrs"].get(key, "")).strip())
    except ValueError:
        return default


def campus_zone(buffer_m=30.0) -> Polygon:
    site = json.loads((SITE_DIR / "osm_site.geojson").read_text(encoding="utf-8"))["features"][0]["geometry"]
    poly = Polygon([_T4326_5186.transform(*c) for c in site["coordinates"][0]])
    return poly.buffer(buffer_m) if buffer_m else poly


# ---------------------------------------------------------------------------
# 1:5,000 연속수치지형도(2024, 논문 폴더) — EPSG:5179를 5186으로
# ---------------------------------------------------------------------------
def load_5000(layer: str, zone) -> list:
    out = []
    gt = layer[2]
    code = layer.split("_", 1)[1]
    minx, miny, maxx, maxy = zone.bounds
    for f in sorted(glob.glob(str(MAP5000 / layer / "*.shp"))):
        r = shapefile.Reader(f, encoding="cp949", encodingErrors="replace")
        names = [x[0] for x in r.fields[1:]]
        for sr in r.iterShapeRecords():
            bb = sr.shape.bbox if gt != "P" else (sr.shape.points[0] * 2 if sr.shape.points else None)
            if not sr.shape.points:
                continue
            g = [tuple(_T5179_5186.transform(*p)) for p in sr.shape.points]
            xs, ys = [p[0] for p in g], [p[1] for p in g]
            if max(xs) < minx or min(xs) > maxx or max(ys) < miny or min(ys) > maxy:
                continue
            parts = list(sr.shape.parts) + [len(g)]
            geom = [g[0]] if gt == "P" else [g[parts[i]:parts[i + 1]] for i in range(len(parts) - 1)]
            rec = {"code": code, "gtype": gt, "geom": geom, "attrs": dict(zip(names, [str(v) for v in sr.record])), "sheet": "5000", "src": "1:5000(2024)"}
            if shape_of(rec).intersects(zone):
                out.append(rec)
        r.close()
    return out


# ---------------------------------------------------------------------------
# 브이월드 건물 가운데 1:1,000에 없는 것(2013년 뒤 건물)
# ---------------------------------------------------------------------------
def new_buildings(feats, zone, min_area=150.0) -> list:
    vw = json.loads((SRC_DIR / "vw_buildings.geojson").read_text(encoding="utf-8"))["features"]
    b1000 = unary_union([shape_of(f) for f in feats if f["code"] == "B0010000" and f["gtype"] == "A"])
    out = []
    for f in vw:
        g = shape(f["geometry"])
        for p in ([g] if g.geom_type == "Polygon" else list(g.geoms)):
            q = Polygon([_T4326_5186.transform(*c) for c in p.exterior.coords])
            if not q.is_valid:
                q = q.buffer(0)
            if q.area > min_area and q.centroid.within(zone) and not q.intersects(b1000):
                out.append(q)
    return out
