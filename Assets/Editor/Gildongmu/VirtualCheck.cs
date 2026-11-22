// 3D 위에서 직접 재서 설계도·경로입력 값과 맞는지 본다(가상 휠체어 대신 위에서 아래로 쏘는 광선).
// 앞뒤 = 가운데선 s±0.5 높이 차, 좌우 = 가로 양 끝(가장자리에서 0.15 m 안) 높이 차, 턱 = 턱 앞뒤 높이 차 − 경사분.
// 기준: 앞뒤·좌우 ±0.3°, 턱 ±2 mm. 실패한 지점은 CheckOutput/virtual_check.csv에 적는다.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEngine;
using UnityEngine.SceneManagement;
using Random = System.Random;

namespace Gildongmu.EditorTools
{
    public static class VirtualCheck
    {
        [Serializable] class RI { public RV[] values; public RB[] barriers; }
        [Serializable] class RV { public int seg; public float s, cross; public float @long; public float[] raw_cross; }
        [Serializable] class RB { public string type; public int seg; public float s, value; }
        [Serializable] class MapData { public MSeg[] segs; }
        [Serializable] class MSeg { public int id; public float len; public float[] p; }

        // 대상지 공용(11/15, 제주대 설계 4장 바 3). 이름 규칙은 RouteView와 같다:
        // Assets/Gildongmu/<Site>/Data/virtual_world.json · <site>_map.json, 장면 루트 <Site>(아래 Paths/Seg_<id>, Buildings, VirtualSign).
        // 인자 없으면 민속촌(전과 같음). 결과 CSV는 민속촌이면 전과 같은 이름, 다른 대상지면 이름 뒤에 _<site>.
        const string DefaultSite = "minsokchon";
        static string DataDir(string site) => Path.Combine(Application.dataPath, $"Gildongmu/{RouteView.SiteName(site)}/Data");
        static string OutCsv(string root, string name, string site) => Path.Combine(root, $"CheckOutput/{name}{(site == DefaultSite ? "" : "_" + site)}.csv");

        public static string Run() => Run(DefaultSite);

        // arg = "site" 또는 "site|경로입력 경로"(프로젝트 폴더 기준 또는 절대 경로). 민속촌은 경로입력을 생략하면 DataPrep/out/경로입력_가상.json.
        public static string Run(string arg)
        {
            var parts = arg.Split('|');
            string site = parts[0].Trim().ToLowerInvariant(), Site = RouteView.SiteName(site); // 대상지 이름은 소문자(경로입력 site와 같음)
            string root = Path.GetDirectoryName(Application.dataPath);
            string riRel = parts.Length > 1 ? parts[1].Trim() : site == DefaultSite ? "DataPrep/out/경로입력_가상.json" : null;
            if (riRel == null) return $"{Site}: 경로입력 경로를 같이 주세요(예: {site}|DataPrep/…/경로입력_가상.json)";
            var w = VirtualWorld.LoadFrom(Path.Combine(DataDir(site), "virtual_world.json"));
            if (w == null) return $"{Site}/Data/virtual_world.json 없음";
            string riPath = Path.Combine(root, riRel), mapPath = Path.Combine(DataDir(site), $"{site}_map.json");
            if (!File.Exists(riPath)) return "경로입력 없음: " + riRel;
            if (!File.Exists(mapPath)) return $"{Site}/Data/{site}_map.json 없음";
            var ri = JsonUtility.FromJson<RI>(File.ReadAllText(riPath));
            var map = JsonUtility.FromJson<MapData>(File.ReadAllText(mapPath));
            var mseg = map.segs.ToDictionary(x => x.id);
            var vseg = w.segs.ToDictionary(x => x.id);
            int roots = SceneManager.GetActiveScene().GetRootGameObjects().Count(g => g.name == Site);
            Physics.SyncTransforms();
            var cols = new Dictionary<int, MeshCollider[]>();
            MeshCollider[] Cols(int id)
            {
                if (!cols.TryGetValue(id, out var c))
                {
                    var g = GameObject.Find($"{Site}/Paths/Seg_{id}");
                    cols[id] = c = g ? g.GetComponentsInChildren<MeshCollider>() : new MeshCollider[0];
                }
                return c;
            }
            float H(int id, Vector3 xz)
            {
                var ray = new Ray(new Vector3(xz.x, 1000, xz.z), Vector3.down);
                float best = float.NaN;
                foreach (var c in Cols(id))
                    if (c.Raycast(ray, out var hit, 2000) && (float.IsNaN(best) || hit.point.y > best)) best = hit.point.y;
                return best;
            }

            var csv = new StringBuilder("종류,구간,s,기대,잰 값,차이\n");
            var rnd = new Random(7);
            // 좌우를 묻지 않은 지점(raw_cross 빈 값, 경로입력 cross는 null이라 JsonUtility가 0으로 읽음)은 좌우 비교에서 뺀다.
            // 급한 꺾임(30° 넘게)에서 길 폭 절반 + 0.6 m 안의 지점은 뺀다: 넓은 길이 꺾이는 곳은 높이가 하나로 정해지지 않아
            // 꺾인 곳을 메운 면이 띠를 덮는다(설계도 값의 문제가 아님). 뺀 수는 결과에 적는다.
            var corners = mseg.Values.Where(x => vseg.ContainsKey(x.id)).ToDictionary(x => x.id, x => VirtualWorld.SharpCorners(x.p, vseg[x.id].len));
            bool NearCorner(RV v) => corners[v.seg].Any(c => Mathf.Abs(c - v.s) < vseg[v.seg].w / 2 + 0.6f);
            var all = ri.values.Where(v => vseg.ContainsKey(v.seg) && !VirtualWorld.InSteps(vseg[v.seg], v.s, 0.6f)).ToList();
            var pool = all.Where(v => !NearCorner(v)).ToList();
            int skipped = all.Count - pool.Count;
            var tilted = pool.Where(v => v.cross >= 2).OrderBy(_ => rnd.Next()).Take(10).ToList();
            var sample = tilted.Concat(pool.Except(tilted).OrderBy(_ => rnd.Next()).Take(50)).ToList();
            int lOk = 0, cOk = 0, n = 0;
            float lMax = 0, cMax = 0;
            foreach (var v in sample)
            {
                var m = mseg[v.seg];
                var g = vseg[v.seg];
                float a = v.s - 0.5f, b = v.s + 0.5f;
                if (a < 0) { a = 0; b = Mathf.Min(1, g.len); }
                if (b > g.len) { a = Mathf.Max(0, g.len - 1); b = g.len; }
                float ha = H(v.seg, VirtualWorld.PointAt(m.p, g.len, a).pos), hb = H(v.seg, VirtualWorld.PointAt(m.p, g.len, b).pos);
                float lg = Mathf.Atan((hb - ha) / (b - a)) * Mathf.Rad2Deg;
                var (pos, dir) = VirtualWorld.PointAt(m.p, g.len, v.s); // 띠의 줄 방향과 같은 선분 방향
                var left = new Vector3(-dir.z, 0, dir.x);
                float off = g.w / 2 - 0.15f;
                float hl = H(v.seg, pos + left * off), hr = H(v.seg, pos - left * off);
                float cr = Mathf.Abs(Mathf.Atan((hl - hr) / (2 * off)) * Mathf.Rad2Deg);
                bool asked = v.raw_cross != null && v.raw_cross.Length > 0;
                float want = asked ? v.cross : VirtualWorld.CrossAt(g, v.s).deg; // 안 물은 지점은 설계도 값과 비교
                float dl = Mathf.Abs(lg - v.@long), dc = Mathf.Abs(cr - want);
                n++;
                if (dl <= 0.3f) lOk++; else csv.AppendLine($"앞뒤,{v.seg},{v.s:F2},{v.@long:F2},{lg:F2},{dl:F2}");
                if (dc <= 0.3f) cOk++; else csv.AppendLine($"좌우,{v.seg},{v.s:F2},{want:F2},{cr:F2},{dc:F2}");
                if (!float.IsNaN(dl)) lMax = Mathf.Max(lMax, dl);
                if (!float.IsNaN(dc)) cMax = Mathf.Max(cMax, dc);
            }

            // 턱은 모두 재되, 급하게 꺾이는 곳(30° 넘게)에서 띠가 겹치는 범위(길 폭 × tan(꺾인 각/2) + 0.6 m, 제주대 작업에서 찾은 식)
            // 안에서 어긋난 턱은 실패로 세지 않고 '꺾임 옆이라 못 잼(참고)'으로 따로 센다. 광선이 다른 가닥을 재기 때문이다.
            // 턱 자리는 지도 자리(제주대 1:1,000 인도 선)일 수 있어 검사에 맞추려고 옮기지 않는다(11/15 팀 결정).
            int bOk = 0, bn = 0, bCorner = 0;
            float bMax = 0;
            bool InCornerZone(MSeg m, VirtualWorld.VSeg g, float s, float half)
            {
                var vs = VirtualWorld.VertexS(m.p, g.len);
                for (int i = 1; i + 1 < m.p.Length / 2; i++)
                {
                    var a = new Vector2(m.p[i * 2] - m.p[i * 2 - 2], m.p[i * 2 + 1] - m.p[i * 2 - 1]);
                    var b = new Vector2(m.p[i * 2 + 2] - m.p[i * 2], m.p[i * 2 + 3] - m.p[i * 2 + 1]);
                    if (a.sqrMagnitude < 1e-12f || b.sqrMagnitude < 1e-12f) continue;
                    float ang = Vector2.Angle(a, b);
                    if (ang <= 30) continue;
                    float reach = g.w * Mathf.Tan(Mathf.Min(ang, 170f) * 0.5f * Mathf.Deg2Rad) + 0.6f;
                    if (Mathf.Abs(vs[i] - s) < reach + half) return true;
                }
                return false;
            }
            foreach (var r in ri.barriers.Where(x => x.type == "bump" && vseg.ContainsKey(x.seg)))
            {
                var g = vseg[r.seg];
                var m = mseg[r.seg];
                var bp = g.bumps.OrderBy(x => Mathf.Abs(x.s - r.s)).First();
                float half = bp.run_mm / 2000f;
                float a = bp.s - half - 0.02f, b = bp.s + half + 0.02f;
                float ha = H(r.seg, VirtualWorld.PointAt(m.p, g.len, a).pos), hb = H(r.seg, VirtualWorld.PointAt(m.p, g.len, b).pos);
                float h0 = H(r.seg, VirtualWorld.PointAt(m.p, g.len, a - 0.3f).pos);
                float slope = (ha - h0) / 0.3f;
                float mm = (hb - ha - slope * (b - a)) * 1000f;
                float want = (bp.dir == "up" ? 1 : -1) * bp.mm;
                float d = Mathf.Abs(mm - want);
                if (!(d <= 2f) && InCornerZone(m, g, bp.s, half))
                {
                    bCorner++;
                    csv.AppendLine($"턱(꺾임 옆이라 못 잼·참고),{r.seg},{bp.s:F2},{want:F0},{mm:F1},{d:F1}");
                    continue;
                }
                bn++;
                if (d <= 2f) bOk++; else csv.AppendLine($"턱,{r.seg},{bp.s:F2},{want:F0},{mm:F1},{d:F1}");
                if (!float.IsNaN(d)) bMax = Mathf.Max(bMax, d);
            }
            File.WriteAllText(OutCsv(root, "virtual_check", site), csv.ToString(), new UTF8Encoding(true));
            return $"앞뒤 {lOk}/{n}, 좌우 {cOk}/{n}, 턱 {bOk}/{bn} 통과, 최대 차이 앞뒤 {lMax:F2}° 좌우 {cMax:F2}° 턱 {bMax:F1} mm, " +
                   $"급한 꺾임 옆이라 뺀 지점 {skipped}/{all.Count}, 꺾임 옆이라 못 잰 턱 {bCorner}(참고), 장면의 {Site} {roots}개";
        }

        // 뜬 것 검사(3D 마무리): 건물 바닥 점이 땅보다 5 cm 넘게 뜨거나, 구간 끝 둥근 판 점이 그 자리 길 표면보다 6 cm 넘게 뜨면 뜬 것.
        // 계단 끝(계단 안 0.01 m)에는 둥근 판이 없어야 한다. 실패는 CheckOutput/virtual_float.csv에 적는다.
        public static string Floating() => Floating(DefaultSite);

        public static string Floating(string arg)
        {
            string site = arg.Trim().ToLowerInvariant(), Site = RouteView.SiteName(site);
            var w = VirtualWorld.LoadFrom(Path.Combine(DataDir(site), "virtual_world.json"));
            if (w == null) return $"{Site}/Data/virtual_world.json 없음";
            string root = Path.GetDirectoryName(Application.dataPath);
            var paths = GameObject.Find($"{Site}/Paths");
            if (!paths) return $"장면에 {Site}/Paths 없음";
            Physics.SyncTransforms();
            var csv = new StringBuilder("종류,이름,x,z,뜬 높이(m)\n");
            var pathsT = paths.transform;
            float PathTop(Vector3 p) // p 자리(위아래 모두)에서 가장 높은 길 표면, 길이 없으면 NaN
            {
                float best = float.NaN;
                foreach (var hit in Physics.RaycastAll(new Vector3(p.x, 1000, p.z), Vector3.down, 2000))
                    if (hit.collider.transform.IsChildOf(pathsT) && (float.IsNaN(best) || hit.point.y > best)) best = hit.point.y;
                return best;
            }
            int bBad = 0, bN = 0; float bMax = 0;
            foreach (var grp in new[] { $"{Site}/Buildings", $"{Site}/BuildingsExtra" })
            {
                var parent = GameObject.Find(grp);
                if (!parent) continue;
                foreach (Transform b in parent.transform)
                {
                    float baseY = b.position.y, worst = float.NegativeInfinity; Vector3 at = default;
                    foreach (var mf in b.GetComponentsInChildren<MeshFilter>())
                        foreach (var v in mf.sharedMesh.vertices)
                        {
                            var q = mf.transform.TransformPoint(v);
                            if (q.y > baseY + 0.01f) continue;
                            float f = q.y - VirtualWorld.TerrainHeight(w, q.x, q.z);
                            if (f > worst) { worst = f; at = q; }
                        }
                    if (float.IsNegativeInfinity(worst)) continue;
                    bN++;
                    bMax = Mathf.Max(bMax, worst);
                    if (worst > 0.05f) { bBad++; csv.AppendLine($"건물,{b.name},{at.x:F1},{at.z:F1},{worst:F3}"); }
                }
            }
            int jBad = 0, jN = 0, jStairs = 0, jGap = 0; float jMax = 0, gMax = 0;
            var vseg = w.segs.ToDictionary(x => x.id);
            foreach (Transform seg in paths.transform)
            {
                if (!int.TryParse(seg.name.Replace("Seg_", ""), out int id) || !vseg.TryGetValue(id, out var v)) continue;
                foreach (Transform j in seg)
                {
                    if (j.name != "JointA" && j.name != "JointB") continue;
                    float e = j.name == "JointA" ? 0 : v.len;
                    if (VirtualWorld.InSteps(v, e, 0.01f)) { jStairs++; csv.AppendLine($"계단 끝 판,{seg.name}/{j.name},,,"); }
                    jN++;
                    // 판 점 아래에 길이 있으면 길 표면과 비교(6 cm 넘으면 뜬 것). 길이 없는 점(길 사이 빈틈을 덮는 몫)은 땅과 비교해 따로 센다(참고).
                    float wp = float.NegativeInfinity, wg = float.NegativeInfinity; Vector3 atP = default, atG = default;
                    var mf = j.GetComponent<MeshFilter>();
                    foreach (var vtx in mf.sharedMesh.vertices)
                    {
                        var q = j.TransformPoint(vtx);
                        float pt = PathTop(q);
                        if (float.IsNaN(pt)) { float f = q.y - VirtualWorld.TerrainHeight(w, q.x, q.z); if (f > wg) { wg = f; atG = q; } }
                        else { float f = q.y - pt; if (f > wp) { wp = f; atP = q; } }
                    }
                    jMax = Mathf.Max(jMax, wp);
                    gMax = Mathf.Max(gMax, wg);
                    if (wp > 0.06f) { jBad++; csv.AppendLine($"끝 판(길 위),{seg.name}/{j.name},{atP.x:F1},{atP.z:F1},{wp:F3}"); }
                    if (wg > 0.06f) { jGap++; csv.AppendLine($"끝 판(빈틈 땅 위),{seg.name}/{j.name},{atG.x:F1},{atG.z:F1},{wg:F3}"); }
                }
            }
            File.WriteAllText(OutCsv(root, "virtual_float", site), csv.ToString(), new UTF8Encoding(true));
            var sign = GameObject.Find($"{Site}/VirtualSign/Front");
            bool signOk = sign && sign.GetComponent<MeshRenderer>().sharedMaterial.GetTexture("_BaseMap") != null && GameObject.Find($"{Site}/VirtualSign/Back");
            return $"뜬 건물 {bBad}/{bN}(최대 {bMax:F2} m), 길 위에서 뜬 끝 판 {jBad}/{jN}(최대 {jMax:F2} m), 빈틈 땅 위로 6 cm 넘는 끝 판 {jGap}(참고, 최대 {gMax:F2} m), 계단 끝 판 {jStairs}개, '가상 세계' 표지 {(signOk ? "있음" : "없음")}";
        }
    }
}
