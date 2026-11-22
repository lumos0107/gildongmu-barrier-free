"""제주대 1:1,000 연결망을 만들어 장소 폴더(jejunu1000)에 쓴다(설계 6장 나).

사용: python -I DataPrep/jejunu/build_net.py
결과: jejunu1000/network.geojson, network_summary.json, kerbs.geojson, entrances.geojson, out/연결망_확인.jpg, out/계단_연결.json
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from shapely.geometry import LineString  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

import common  # noqa: E402
import net_graph as NG  # noqa: E402
import net_parts as NP  # noqa: E402
import terrain as TR  # noqa: E402
from common import OUT, SITE_DIR, SRC_DIR, campus_zone, load_1000, load_5000, load_geo, new_buildings, shape_of  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
TRACED = pathlib.Path(__file__).resolve().parent / "traced_paths.json"


def _points_geojson(path, pts, geo, extra_keys):
    feats = []
    for p in pts:
        lon, lat = geo.from5186(*p["xy"])
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]},
                      "properties": {k: p[k] for k in extra_keys if k in p}})
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")


def _cut_new_buildings(parts, nb):
    if not nb:
        return parts
    u = unary_union([b.buffer(-0.3) for b in nb])
    out = []
    for p in parts:
        g = p["geom"].difference(u) if p["geom"].intersects(u) else p["geom"]
        for gg in NP._lines(g):
            if gg.length >= 0.5:
                out.append({**p, "geom": gg})
    return out


def build(verbose=True):
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    feats = load_1000()
    zone = campus_zone()
    geo, geo_full = load_geo(), load_geo("aerial_z19_full.json")
    osm = json.loads((SRC_DIR / "network.geojson").read_text(encoding="utf-8"))
    pub = NP.public_roads(feats, zone)
    camp = NP.campus_roads(osm, geo, zone, pub, feats)
    roads = pub + camp
    sw = NP.sidewalks(feats, zone, roads)
    NP.mark_walkable(roads, sw)
    nb = new_buildings(feats, campus_zone(0))
    ter = TR.build_terrain(feats, geo)

    def grad(x, y, h=2.0):
        return ((TR.height_5186(ter, geo, x + h, y) - TR.height_5186(ter, geo, x - h, y)) / (2 * h),
                (TR.height_5186(ter, geo, x, y + h) - TR.height_5186(ter, geo, x, y - h)) / (2 * h))
    st = NP.stairs(feats, zone, grad=grad)
    img = np.asarray(Image.open(SITE_DIR / "aerial_z19_full.jpg").convert("RGB"))
    cx, kerbs = NP.crossings(sw, roads, feats, img, geo_full)
    traced = NG.traced_parts(TRACED, geo_full)
    stop = [f for f in feats if f["code"] == "A0140000" and "정문" in f["attrs"].get("명칭", "")]
    start = stop[0]["geom"][0] if stop else zone.centroid.coords[0]
    # 1) 계단 출입까지 잇고, 2) 정문에서 계단 없이 닿는 길에만 계단 없는 출입구(가상)를 잇는다(최종 검토 Important 3)
    en, en_pts = NP.entrances(feats, zone, st, [], nb, steps=True, stepfree=False)
    base = [r for r in roads if r["props"].get("walk")] + sw + cx + traced + en
    sl = NG.short_links(st, base)
    raw = _cut_new_buildings(roads + sw + st + cx + traced + en + sl, nb)
    parts0 = NG.prune_stubs(NG.assemble(raw))
    reach = [p for p in NG.stepfree_reachable(parts0, start) if p["props"].get("kind") != "entrance"]
    en2, en_pts2 = NP.entrances(feats, zone, st, reach, nb, steps=False, stepfree=True)
    en, en_pts = en + en2, en_pts + en_pts2
    raw = _cut_new_buildings(en2, nb) + raw
    parts = NG.prune_stubs(NG.assemble(raw))
    # 양 끝이 모두 떨어진 계단은 연결망에서 뺀다(한쪽만 이어진 계단은 막다른 길로 둔다)
    stat = NG.stair_status(st, parts)
    dead = {s["props"]["osm"] for s, ok in stat if not any(ok)}
    parts = [p for p in parts if not (p["props"].get("highway") == "steps" and p["props"].get("osm") in dead)]
    summ = NG.write_network(parts, geo, SITE_DIR, start)
    _points_geojson(SITE_DIR / "kerbs.geojson", kerbs, geo, ("kind", "src"))
    _points_geojson(SITE_DIR / "entrances.geojson", en_pts, geo, ("building", "name", "kind", "src"))
    # 계단 연결 상태와 못 이은 계단 목록(traced_paths.json의 skipped_stairs에 까닭과 함께 적는다)
    tr = json.loads(TRACED.read_text(encoding="utf-8"))
    why = {m["osm"]: m["why"] for m in tr.get("manual", []) if "osm" in m}
    loose = [{"osm": s["props"]["osm"], "ends": [list(s["geom"].coords[0]), list(s["geom"].coords[-1])], "ok": ok}
             for s, ok in stat if not all(ok)]
    tr["skipped_stairs"] = [{"ufid": x["osm"], "kept": any(x["ok"]),
                             "why": ("한쪽 끝만 이음(막다른 계단으로 둠): " if any(x["ok"]) else "양 끝 모두 못 이음(연결망에서 뺌): ")
                             + why.get(x["osm"], "항공사진에서 이을 길을 찾지 못함")} for x in loose]
    TRACED.write_text(json.dumps(tr, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "계단_연결.json").write_text(json.dumps({"stairs": len(st), "connected": len(st) - len(loose), "loose": loose,
                                                   "removed": sorted(dead)}, ensure_ascii=False, indent=1), encoding="utf-8")
    # 1:5,000(2024) 인도 가운데 1:1,000 인도에서 5 m 넘게 떨어진 것(2013년 뒤 보도 후보)
    curb_u = unary_union([s["curb"] for s in sw] + [s["geom"] for s in sw])
    new5000 = [shape_of(f) for f in load_5000("N3L_A0033320", zone)]
    new5000 = [g for g in new5000 if g.geom_type == "LineString" and g.distance(curb_u) > 5.0]
    marks = [((c[0], c[1]), (255, 0, 0)) for x in loose for c, ok in zip(x["ends"], x["ok"]) if not ok]
    NG.check_image(parts, geo_full, SITE_DIR / "aerial_z19_full.jpg", OUT / "연결망_확인.jpg",
                   extra=[(g, (160, 0, 255)) for g in new5000], marks=marks)
    comps = NG.components(parts)
    kinds = {}
    for p in parts:
        k = p["props"]["kind"]
        kinds[k] = kinds.get(k, 0.0) + p["geom"].length
    if verbose:
        print(f"선 {len(parts)}개, 종류별 m {({k: round(v) for k, v in sorted(kinds.items())})}")
        print(f"차도 {len(roads)}(걷는 차도 {sum(1 for r in roads if r['props'].get('walk'))}), 보도 {len(sw)}, 계단 {len(st)}(이음 {len(st) - len(loose)}), "
              f"건너는 곳 {len(cx)}, 계단 끝 짧은 잇기 {len(sl)}, 턱 점 {len(kerbs)}, 출입 {len(en_pts)}(계단 없는 출입 {sum(1 for p in en_pts if p['kind'] == 'stepfree')}), 그린 길 {len(traced)}")
        print(f"조각 {len(comps)}개, 가장 큰 조각 비율 {comps[0] / sum(comps):.3f}, 1:5000 새 보도 후보 {len(new5000)}줄, 출발 {summ['start']}")
    return parts, st, loose


if __name__ == "__main__":
    build()
