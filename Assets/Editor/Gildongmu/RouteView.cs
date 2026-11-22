// 경로 추천 앱 첫 판의 결과(bf-route-result-1, DataPrep/route_engine.py)를 3D 맵 위에 색으로 칠한다.
// 설계: Docs/2026-11-15-경로앱-설계.md 5장(띠는 길 표면 위 약 8 cm). 대상지는 결과 파일의 site로 찾는다(Assets/Gildongmu/<Site>/Data/virtual_world.json, <site>_map.json).
// 색: 갈 수 있음 파랑, 불확실 주황, 막힘 빨강(끊어 그림). 가상 자료(test)면 출발 쪽에 '가상 세계' 판을 세운다.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace Gildongmu.EditorTools
{
    public static class RouteView
    {
        [Serializable] class RR { public string format, site, mode, status; public bool test, found; public float length_m; public RPt from, to; public RStep[] steps; }
        [Serializable] class RPt { public string name; public int seg; public float s; }
        [Serializable] class RStep { public int seg; public float s0, s1; public string state; }
        [Serializable] class MapData { public MSeg[] segs; }
        [Serializable] class MSeg { public int id; public float len; public float[] p; }

        // 길 띠는 높이 단면 + 0.05 m에 그려지므로(MinsokchonMaker.VirtualRibbon), 경로 띠는 그보다 8 cm 위
        const float Lift = 0.13f, Half = 0.5f, HaloHalf = 0.75f; // 띠 폭 1 m, 아래 흰 테두리 1.5 m(땅 · 노면 색과 구분)

        internal static string SiteName(string site) => string.IsNullOrEmpty(site) ? "Minsokchon" : char.ToUpper(site[0]) + site.Substring(1);

        static (RR r, VirtualWorld.World w, Dictionary<int, MSeg> map, GameObject root, string err) Open(string resultPath)
        {
            if (!File.Exists(resultPath)) return (null, null, null, null, "결과 파일 없음: " + resultPath);
            var r = JsonUtility.FromJson<RR>(File.ReadAllText(resultPath));
            if (r == null || r.format != "bf-route-result-1") return (null, null, null, null, "bf-route-result-1 형식이 아님");
            string site = SiteName(r.site), dir = Path.Combine(Application.dataPath, $"Gildongmu/{site}/Data");
            var w = VirtualWorld.LoadFrom(Path.Combine(dir, "virtual_world.json"));
            var mapFile = Path.Combine(dir, $"{r.site}_map.json");
            if (w == null || !File.Exists(mapFile)) return (r, null, null, null, $"{site} 자료 없음(virtual_world.json, {r.site}_map.json)");
            var map = JsonUtility.FromJson<MapData>(File.ReadAllText(mapFile)).segs.ToDictionary(x => x.id);
            var root = GameObject.Find(site);
            if (!root) return (r, w, map, null, $"장면에 {site} 없음");
            return (r, w, map, root, null);
        }

        // 길 표면 위 띠의 가운데 선 점들(s0 → s1, 0.5 m마다)
        static List<(Vector3 c, Vector3 left)> Line(VirtualWorld.VSeg v, MSeg m, float s0, float s1)
        {
            var pts = new List<(Vector3, Vector3)>();
            int n = Mathf.Max(1, Mathf.CeilToInt(Mathf.Abs(s1 - s0) / 0.5f));
            for (int i = 0; i <= n; i++)
            {
                float s = Mathf.Lerp(s0, s1, (float)i / n);
                var pos = VirtualWorld.PointAt(m.p, v.len, s).pos;
                var d = VirtualWorld.SmoothDir(m.p, v.len, s);
                pos.y = VirtualWorld.ProfileHeight(v, s) + Lift;
                pts.Add((pos, new Vector3(-d.z, 0, d.x)));
            }
            return pts;
        }

        static Mesh Ribbon(List<(Vector3 c, Vector3 left)> pts, string name, float half = Half, float drop = 0)
        {
            var vs = new List<Vector3>();
            var tris = new List<int>();
            foreach (var (c, left) in pts) { var q = c + Vector3.down * drop; vs.Add(q + left * half); vs.Add(q - left * half); }
            for (int i = 0; i + 1 < pts.Count; i++)
            {
                int a = i * 2;
                tris.AddRange(new[] { a, a + 2, a + 1, a + 1, a + 2, a + 3 });
                tris.AddRange(new[] { a, a + 1, a + 2, a + 1, a + 3, a + 2 }); // 양면
            }
            var mesh = new Mesh { name = name };
            mesh.SetVertices(vs);
            mesh.SetTriangles(tris, 0);
            mesh.RecalculateNormals();
            mesh.RecalculateBounds();
            return mesh;
        }

        static Material Mat(string name, Color c)
        {
            const string dir = "Assets/Gildongmu/Route";
            if (!AssetDatabase.IsValidFolder(dir)) AssetDatabase.CreateFolder("Assets/Gildongmu", "Route");
            string path = $"{dir}/{name}.mat";
            var m = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (!m) { m = new Material(Shader.Find("Universal Render Pipeline/Unlit")); AssetDatabase.CreateAsset(m, path); }
            m.SetColor("_BaseColor", c);
            EditorUtility.SetDirty(m);
            return m;
        }

        static GameObject Obj(GameObject parent, string name, Mesh mesh, Material mat)
        {
            var g = new GameObject(name);
            g.transform.SetParent(parent.transform, false);
            g.AddComponent<MeshFilter>().sharedMesh = mesh;
            g.AddComponent<MeshRenderer>().sharedMaterial = mat;
            return g;
        }

        static GameObject Pole(GameObject parent, string name, Vector3 at, Material mat)
        {
            var g = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            g.name = name;
            UnityEngine.Object.DestroyImmediate(g.GetComponent<Collider>());
            g.transform.SetParent(parent.transform, false);
            g.transform.position = at + Vector3.up * 1.5f;
            g.transform.localScale = new Vector3(0.35f, 1.5f, 0.35f);
            g.GetComponent<MeshRenderer>().sharedMaterial = mat;
            return g;
        }

        public static string Show(string resultPath)
        {
            var (r, w, map, root, err) = Open(resultPath);
            if (err != null) return err;
            var old = root.transform.Find("Route");
            if (old) UnityEngine.Object.DestroyImmediate(old.gameObject);
            var route = new GameObject("Route");
            route.transform.SetParent(root.transform, false);
            var vseg = w.segs.ToDictionary(x => x.id);
            var mats = new Dictionary<string, Material>
            {
                ["ok"] = Mat("Route_ok", new Color32(0x34, 0x61, 0xB0, 255)),
                ["uncertain"] = Mat("Route_uncertain", new Color32(0xE8, 0x76, 0x2B, 255)),
                ["blocked"] = Mat("Route_blocked", new Color32(0xD6, 0x45, 0x45, 255)),
            };
            var ink = Mat("Route_pole", new Color32(0x28, 0x28, 0x28, 255));
            var halo = Mat("Route_halo", new Color32(0xFF, 0xFF, 0xFF, 255));
            int k = 0;
            foreach (var st in r.steps ?? new RStep[0])
            {
                if (!vseg.TryGetValue(st.seg, out var v) || !map.TryGetValue(st.seg, out var m)) return $"구간 {st.seg} 자료 없음";
                var pts = Line(v, m, st.s0, st.s1);
                var step = new GameObject($"Step_{k++}_{st.seg}_{st.state}");
                step.transform.SetParent(route.transform, false);
                Obj(step, "Halo", Ribbon(pts, $"RouteHalo_{st.seg}", HaloHalf, 0.015f), halo);
                if (st.state == "blocked" && pts.Count < 3) // 0.5 m 이하로 짧은 막힘은 한 토막으로
                    Obj(step, "Dash_0", Ribbon(pts, $"RouteDash_{st.seg}_0"), mats["blocked"]);
                else if (st.state == "blocked") // 막힘은 1 m씩 끊어 그린다
                {
                    for (int i = 0; i + 2 < pts.Count; i += 4)
                        Obj(step, $"Dash_{i}", Ribbon(pts.GetRange(i, Mathf.Min(3, pts.Count - i)), $"RouteDash_{st.seg}_{i}"), mats["blocked"]);
                }
                else Obj(step, "Ribbon", Ribbon(pts, $"Route_{st.seg}"), mats.TryGetValue(st.state, out var mt) ? mt : mats["ok"]);
            }
            Vector3 P(RPt p)
            {
                var v = vseg[p.seg];
                var pos = VirtualWorld.PointAt(map[p.seg].p, v.len, p.s).pos;
                pos.y = VirtualWorld.ProfileHeight(v, p.s);
                return pos;
            }
            if (r.from != null && vseg.ContainsKey(r.from.seg)) Pole(route, "Start", P(r.from), ink);
            if (r.to != null && vseg.ContainsKey(r.to.seg)) Pole(route, "Goal", P(r.to), ink);
            if (r.test && r.from != null && vseg.ContainsKey(r.from.seg))
            {
                var sign = AssetDatabase.LoadAssetAtPath<Material>($"Assets/Gildongmu/{SiteName(r.site)}/Materials/VirtualSign.mat");
                if (sign)
                    foreach (var (nm, yaw) in new[] { ("VirtualLabel_F", 0f), ("VirtualLabel_B", 180f) }) // 앞뒤 두 면
                    {
                        var q = GameObject.CreatePrimitive(PrimitiveType.Quad);
                        q.name = nm;
                        UnityEngine.Object.DestroyImmediate(q.GetComponent<Collider>());
                        q.transform.SetParent(route.transform, false);
                        q.transform.SetPositionAndRotation(P(r.from) + Vector3.up * 3.6f, Quaternion.Euler(0, yaw, 0));
                        q.transform.localScale = new Vector3(2.4f, 0.9f, 1);
                        q.GetComponent<MeshRenderer>().sharedMaterial = sign;
                    }
            }
            return $"경로 그림: {r.from?.name} → {r.to?.name} · {r.mode} · {r.status} · {r.length_m:F0} m · 단계 {k}" + (r.test ? " · 가상 자료" : "");
        }

        // 그린 길(Route)을 지우고 장면을 저장한다(저장 안 한 변경이 남으면 장면 열기 도구가 멈춤)
        public static string Clear()
        {
            int n = 0;
            foreach (var root in UnityEngine.SceneManagement.SceneManager.GetActiveScene().GetRootGameObjects())
            {
                var t = root.transform.Find("Route");
                if (t) { UnityEngine.Object.DestroyImmediate(t.gameObject); n++; }
            }
            UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(UnityEngine.SceneManagement.SceneManager.GetActiveScene());
            UnityEditor.SceneManagement.EditorSceneManager.SaveOpenScenes();
            return $"그린 길 {n}개 지우고 장면 저장";
        }

        // 띠가 단계마다 하나씩 있고, 띠 꼭짓점이 그 자리 길 표면보다 3~20 cm 위인지 광선으로 잰다.
        public static string Check(string resultPath)
        {
            var (r, w, map, root, err) = Open(resultPath);
            if (err != null) return "실패: " + err;
            var route = root.transform.Find("Route");
            if (!route) return "실패: Route 없음";
            int steps = (r.steps ?? new RStep[0]).Length, drawn = route.Cast<Transform>().Count(t => t.name.StartsWith("Step_"));
            // 단계마다 색 띠(Ribbon 또는 Dash)가 적어도 하나 있어야 한다(흰 테두리만 있으면 안 됨)
            int colored = route.Cast<Transform>().Count(t => t.name.StartsWith("Step_") &&
                t.Cast<Transform>().Any(c => c.name.StartsWith("Ribbon") || c.name.StartsWith("Dash")));
            Physics.SyncTransforms();
            var paths = root.transform.Find("Paths");
            if (!paths) return "실패: 장면에 Paths 없음";
            int n = 0, ok = 0, miss = 0;
            var ds = new List<float>();
            foreach (var mf in route.GetComponentsInChildren<MeshFilter>())
            {
                if (!mf.name.StartsWith("Ribbon") && !mf.name.StartsWith("Dash")) continue;
                foreach (var vtx in mf.sharedMesh.vertices)
                {
                    var q = mf.transform.TransformPoint(vtx);
                    float best = float.NaN;
                    foreach (var hit in Physics.RaycastAll(new Vector3(q.x, q.y + 3, q.z), Vector3.down, 10))
                        if (hit.collider.transform.IsChildOf(paths) && (float.IsNaN(best) || hit.point.y > best)) best = hit.point.y;
                    if (float.IsNaN(best)) { miss++; continue; }
                    n++;
                    float d = q.y - best;
                    ds.Add(d);
                    if (d >= 0.03f && d <= 0.2f) ok++;
                }
            }
            bool pass = drawn == steps && colored == steps && steps > 0 && n > 0 && ok >= 0.95f * n && miss <= 0.05f * (n + miss);
            ds.Sort();
            string dist = ds.Count > 0 ? $", 높이 차 최소 {ds[0]:F3} · 가운데 {ds[ds.Count / 2]:F3} · 최대 {ds[ds.Count - 1]:F3} m" : "";
            return $"{(pass ? "통과" : "실패")}: 띠 {drawn}/{steps}(색 띠 있는 단계 {colored}), 길 위 높이 맞는 꼭짓점 {ok}/{n}, 길 밖 꼭짓점 {miss}{dist}";
        }
    }
}
