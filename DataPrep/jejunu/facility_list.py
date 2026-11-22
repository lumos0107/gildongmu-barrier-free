"""제주대 시설 목록(경로 추천의 출발·도착지) jejunu1000/시설목록.geojson (계획 Task 10).

칸은 minsokchon/시설목록.geojson과 같고 src를 더한다. 경로 엔진은 name, no, seg, aerial_px를 쓴다.
- 건물: 이름(1:1,000 주기) 있는 건물마다 하나. 자리는 계단 없는 출입구(가상) 점. 같은 이름은 가장 큰 건물 하나.
- 버스정류장: 1:1,000 A0140000(같은 이름은 하나).
- seg: 가장 가까운 계단 없는 구간(0.5 m 안으로 비슷하면 그중 가까운 것). aerial_px는 pack segs[].xy와 같은 18단계 화소.

사용: python -I DataPrep/jejunu/facility_list.py --map out/jejunu1000_map.json --world out/virtual_world.json
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from shapely.geometry import Point  # noqa: E402

import common  # noqa: E402
import virtual_world as vw  # noqa: E402
from common import SITE_DIR, campus_zone, load_1000, load_geo, shape_of  # noqa: E402
from net_parts import building_name  # noqa: E402


def stepfree_segs(pack, steps_of):
    """출발 마디에서 계단 구간을 지나지 않고 닿는 구간."""
    adj = {}
    for s in pack["segs"]:
        if steps_of.get(s["seg"]):
            continue
        adj.setdefault(s["a"], []).append((s["b"], s["seg"]))
        adj.setdefault(s["b"], []).append((s["a"], s["seg"]))
    seen, segs, st = {pack["start_node"]}, set(), [pack["start_node"]]
    while st:
        u = st.pop()
        for v, sid in adj.get(u, []):
            segs.add(sid)
            if v not in seen:
                seen.add(v)
                st.append(v)
    return segs


def nearest_seg(mp_segs, steps_of, xz, ok=None):
    cand = []
    for s in mp_segs:
        if steps_of.get(s["id"]) or s["a"] == s["b"] or (ok is not None and s["id"] not in ok):
            continue
        sx, d = vw.project(s, xz)
        cand.append((d, s["id"]))
    d, sid = min(cand)
    return sid, round(d, 1)


def build(map_path, world_path, pack_path):
    mp = json.loads(pathlib.Path(map_path).read_text(encoding="utf-8"))
    world = json.loads(pathlib.Path(world_path).read_text(encoding="utf-8"))
    pack = json.loads(pathlib.Path(pack_path).read_text(encoding="utf-8"))
    steps_of = {s["id"]: s["steps"] for s in world["segs"]}
    ok = stepfree_segs(pack, steps_of)  # 경로 추천의 출발·도착지는 계단 없이 닿아야 한다(최종 검토 Important 3)
    geo = load_geo()
    feats = load_1000()
    zone = campus_zone()
    blds = [(shape_of(f), building_name(f), f) for f in feats if f["code"] == "B0010000" and f["gtype"] == "A"]
    ents = json.loads((SITE_DIR / "entrances.geojson").read_text(encoding="utf-8"))["features"]
    best = {}
    for e in ents:
        p = e["properties"]
        if p["kind"] != "stepfree" or not p.get("name"):
            continue
        lon, lat = e["geometry"]["coordinates"]
        x5, y5 = geo.to5186(lon, lat)
        g = min(blds, key=lambda b: b[0].distance(Point(x5, y5)))[0]
        if p["name"] not in best or g.area > best[p["name"]][0]:
            best[p["name"]] = (g.area, lon, lat, g)
    out = []

    def add(name, typ, how, err, lon, lat, building, src):
        px = geo.px(lon, lat)
        xz = geo.unity(*px)
        sid, d = nearest_seg(mp["segs"], steps_of, xz, ok)
        out.append({"type": "Feature", "properties": {"no": len(out) + 1, "name": name, "type": typ, "how": how, "est_error_m": err,
                                                      "aerial_px": [round(px[0], 1), round(px[1], 1)], "building": building,
                                                      "seg": sid, "seg_dist_m": d, "src": src},
                    "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]}})
    for name in sorted(best):
        area, lon, lat, g = best[name]
        c = g.centroid
        cx, cz = geo.unity_from5186(c.x, c.y)
        add(name, "building", "1:1000 주기(건물 이름)", 10, lon, lat,
            {"name": name, "kind": "modern", "cx": round(cx, 2), "cz": round(cz, 2), "dist_m": 0.0}, "가상(출입구 자리), 건물은 1:1000")
    # 정문: 1:1,000 문주(정문 기둥) 가운데에서 가장 가까운, 계단 없이 닿는 길 위 점(팀 결정 2026-11-15)
    stop = [f for f in feats if f["code"] == "A0140000" and "정문" in f["attrs"].get("명칭", "")]
    if stop:
        sp = Point(stop[0]["geom"][0])
        pillars = [f for f in feats if f["code"] == "B0020000" and f["attrs"].get("구분", "").strip() == "문주" and shape_of(f).distance(sp) <= 80]
        if pillars:
            cx = sum(shape_of(f).centroid.x for f in pillars) / len(pillars)
            cy = sum(shape_of(f).centroid.y for f in pillars) / len(pillars)
            gxz = geo.unity_from5186(cx, cy)
            sid, d = nearest_seg(mp["segs"], steps_of, gxz, ok)
            seg = next(s for s in mp["segs"] if s["id"] == sid)
            sx, _ = vw.project(seg, gxz)
            px, pz = vw.point_at(seg, sx)[0]
            ppx = geo.unity_inv(px, pz)
            lon, lat = geo.lonlat(*ppx)
            out.append({"type": "Feature", "properties": {
                "no": len(out) + 1, "name": "제주대학교정문", "type": "gate",
                "how": f"1:1000 문주(정문 기둥 {len(pillars)}개) 가운데에서 가장 가까운 길 위 점({round(d, 1)} m)",
                "est_error_m": round(d, 1), "aerial_px": [round(ppx[0], 1), round(ppx[1], 1)], "building": None,
                "seg": sid, "seg_dist_m": 0.0, "src": f"{pillars[0]['src']} 문주(정문 자리), 길 위 점"},
                "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]}})
    seen = {"제주대학교정문"}
    for f in feats:
        if f["code"] != "A0140000" or f["gtype"] != "P":
            continue
        nm = f["attrs"].get("명칭", "").strip() or "버스정류장"
        name = f"{nm} 버스정류장" if "정류장" not in nm else nm
        if name in seen or name in best or not Point(f["geom"][0]).within(zone):
            continue
        seen.add(name)
        lon, lat = geo.from5186(*f["geom"][0])
        add(name, "bus_stop", "1:1000 버스정류장", 0, lon, lat, None, f["src"])
    return {"type": "FeatureCollection", "source": "1:1000 수치지형도 건물 이름·버스정류장(제주대 아라캠퍼스), 건물 자리는 계단 없는 출입구(가상)",
            "features": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default=str(common.OUT / "jejunu1000_map.json"))
    ap.add_argument("--world", default=str(common.OUT / "virtual_world.json"))
    ap.add_argument("--pack", required=True)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    fc = build(a.map, a.world, a.pack)
    (SITE_DIR / "시설목록.geojson").write_text(json.dumps(fc, ensure_ascii=False, indent=1), encoding="utf-8")
    t = [f["properties"]["type"] for f in fc["features"]]
    print(f"시설 {len(t)}곳(건물 {t.count('building')}, 버스정류장 {t.count('bus_stop')}) -> {SITE_DIR / '시설목록.geojson'}")


if __name__ == "__main__":
    main()
