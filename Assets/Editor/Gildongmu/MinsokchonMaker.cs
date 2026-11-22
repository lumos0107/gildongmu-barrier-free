// 제주민속촌 3D 맵: DataPrep/export_minsokchon.py가 만든 JSON과 항공사진으로 Minsokchon 장면을 만든다.
// 좌표: 항공사진 가운데가 원점, x = 동쪽 m, z = 북쪽 m. 땅은 평면(고도 자료 없음).
// 길 구간 오브젝트 이름(Seg_<번호>)은 측정 앱 묶음의 구간 번호와 같다.
// virtual_world.json(가상 세계 설계도)이 있으면 땅 높낮이, 기울어진 길, 턱, 계단, 노면 재질을 그대로 짓는다.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using Object = UnityEngine.Object;
using Random = System.Random;

namespace Gildongmu.EditorTools
{
    public static class MinsokchonMaker
    {
        const string Dir = "Assets/Gildongmu/Minsokchon";
        const string ScenePath = "Assets/Scenes/Minsokchon.unity";
        const string MeshPath = Dir + "/MinsokchonMeshes.asset";
        const float TreeTile = 80f;

        [Serializable] class MapData { public string name; public float mpp, sizeM; public float[] start; public float[] boundary; public Seg[] segs; public Line[] steps; public Bld[] buildings; public float[] trees; }
        [Serializable] class Seg { public int id; public bool road, drawn; public float len, w; public float[] p; }
        [Serializable] class Line { public float[] p; }
        [Serializable] class Bld { public string kind, name; public int floors, front; public float cx, cz, w, d, ang; public float[] roof, ring; public int[] tris; }

        static readonly Dictionary<string, Material> mats = new Dictionary<string, Material>();
        static bool storeMade;

        [MenuItem("길동무/민속촌 만들기")]
        public static string Make()
        {
            OpenScene();
            var data = JsonUtility.FromJson<MapData>(File.ReadAllText(Path.Combine(Application.dataPath, "Gildongmu/Minsokchon/Data/minsokchon_map.json")));
            mats.Clear();
            AssetDatabase.DeleteAsset(MeshPath);
            storeMade = false;
            var rnd = new Random(7);
            var vw = VirtualWorld.Load();
            groundFn = vw == null ? (Func<float, float, float>)((x, z) => 0f) : (x, z) => VirtualWorld.TerrainHeight(vw, x, z);

            var root = new GameObject("Minsokchon");
            if (vw != null) VirtualGround(Child(root, "Ground"), data.sizeM, vw);
            else Ground(Child(root, "Ground"), data.sizeM);

            var paths = Child(root, "Paths");
            var vsegs = vw?.segs.ToDictionary(v => v.id);
            var byNode = vw?.segs.SelectMany(v => new[] { (n: v.a, v), (n: v.b, v) }).Distinct().ToLookup(x => x.n, x => x.v);
            int nPieces = 0;
            foreach (var s in data.segs)
            {
                if (vsegs != null && vsegs.TryGetValue(s.id, out var v)) { nPieces += VirtualPath(paths, s, v, byNode); continue; }
                var pts = Pts(s.p);
                string mat = s.road ? "Road" : s.drawn ? "Trail" : "Walk";
                float y = s.road ? 0.03f : s.drawn ? 0.04f : 0.05f;
                MeshObj(paths, $"Seg_{s.id}", Ribbon(pts, s.w, y), mat);
            }
            var steps = Child(root, "Steps");
            if (vw == null) foreach (var l in data.steps) Stairs(steps, Pts(l.p));

            var houses = Child(root, "Buildings");
            int nThatch = 0, nTile = 0, nModern = 0;
            for (int i = 0; i < data.buildings.Length; i++)
            {
                var b = data.buildings[i];
                if (b.kind == "thatch") { Thatch(houses, b, i); nThatch++; }
                else if (b.kind == "tile") { Tile(houses, b, i); nTile++; }
                else { Modern(houses, b, i); nModern++; }
            }

            int nExtra = 0, nWall = 0, nObs = 0, nFac = 0;
            if (vw != null)
            {
                var extraParent = Child(root, "BuildingsExtra");
                for (int i = 0; i < (vw.buildings_extra?.Length ?? 0); i++)
                {
                    var e = vw.buildings_extra[i];
                    var b = new Bld { kind = e.kind, name = "", floors = e.floors, front = e.front, cx = e.cx, cz = e.cz, w = e.w, d = e.d, ang = e.ang, roof = e.roof, ring = e.ring, tris = e.tris };
                    int k = 1000 + i;
                    if (e.kind == "thatch") Thatch(extraParent, b, k);
                    else if (e.kind == "tile") Tile(extraParent, b, k);
                    else if (e.kind == "greenhouse") Greenhouse(extraParent, b, k);
                    else Modern(extraParent, b, k);
                    nExtra++;
                }
                nWall = Walls(Child(root, "Walls"), vw.walls);
                Fences(Child(root, "Fences"), vw.fences);
                Ponds(Child(root, "Water"), vw.water);
                nObs = Obstacles(Child(root, "Obstacles"), data.segs, vw);
                nFac = Facilities(Child(root, "Facilities"), data.segs, vw);
            }
            int nTrees = Trees(Child(root, "Trees"), data.trees, rnd);
            Gate(root, new Vector3(data.start[0], groundFn(data.start[0], data.start[1]), data.start[1]));
            if (vw != null) VirtualSign(root, data);

            SetupLook();
            var over = View(root, "ViewOverview", new Vector3(10, 400, -330), new Vector3(5, 0, 45));
            View(root, "ViewVillage", new Vector3(-5, 38, -215), new Vector3(-60, 0, -125));
            View(root, "ViewTile", new Vector3(55, 30, -75), new Vector3(100, 0, -10));
            View(root, "ViewGate", new Vector3(118, 7, 192), new Vector3(70, 0, 135));
            WalkView(root, data.segs, new Vector2(-55, -120));
            string extra = "";
            if (vw != null)
            {
                VirtualViews(root, data.segs, vw);
                extra = $", 땅 {vw.terrain.n}x{vw.terrain.n}, 턱 {vw.segs.Sum(v => v.bumps.Length)}, 계단 {vw.segs.Sum(v => v.steps.Length)}, 재질 토막 {nPieces}" +
                        $", 더한 건물 {nExtra}동, 돌담 {nWall}줄, 울타리 {vw.fences?.Length ?? 0}줄, 연못 {vw.water?.Length ?? 0}곳" +
                        $", 3D 장애물 {nObs}개, 3D 시설 {nFac}개";
            }
            var cam = Camera.main;
            cam.transform.SetPositionAndRotation(over.transform.position, over.transform.rotation);
            cam.farClipPlane = 5000;

            EditorSceneManager.SaveScene(root.scene);
            AssetDatabase.SaveAssets();
            SceneView.lastActiveSceneView?.AlignViewToObject(cam.transform);
            return $"민속촌 만듦: 길 {data.segs.Length}구간, 계단 {data.steps.Length}줄, 초가 {nThatch}·기와 {nTile}·현대 {nModern}동, 나무 {nTrees}그루{extra}";
        }

        // 땅 높이(가상 설계도가 없으면 0)
        static Func<float, float, float> groundFn = (x, z) => 0f;

        // 길 위 s 자리, 가로로 lateral(m, 왼쪽 +)만큼 옮긴 곳의 길 표면 위치와 진행 방향
        static (Vector3 pos, Vector3 dir, Vector3 left) OnPath(Seg s, VirtualWorld.VSeg v, float at, float lateral = 0)
        {
            var (p, dir) = VirtualWorld.PointAt(s.p, v.len, Mathf.Clamp(at, 0, v.len));
            var left = new Vector3(-dir.z, 0, dir.x);
            var q = p + left * lateral;
            float h = VirtualWorld.ProfileHeight(v, at) + 0.05f;
            q.y = Mathf.Abs(lateral) > v.w / 2 + 0.2f ? groundFn(q.x, q.z) : h;
            return (q, dir, left);
        }

        static void Sign(GameObject parent, string name, Vector3 at, string mat, float h = 1.8f)
        {
            var g = Child(parent, name);
            g.transform.position = at;
            Prim(g, PrimitiveType.Cylinder, "Pole", new Vector3(0, h / 2, 0), Vector3.zero, new Vector3(0.07f, h / 2, 0.07f), "Bark");
            Prim(g, PrimitiveType.Cube, "Board", new Vector3(0, h, 0), Vector3.zero, new Vector3(0.6f, 0.4f, 0.05f), mat);
        }

        // 2·3차 장애물(가상) 3D: 좁은 곳(화분), 틈(배수구 덮개), 못 감(돌), 끊긴 길(막이), 낙차(난간·턱·낮은 땅), 일시 막힘(고깔), 물 고임, 표에 없는 것
        static int Obstacles(GameObject parent, Seg[] segs, VirtualWorld.World w)
        {
            if (w.obstacles == null) return 0;
            var map = segs.ToDictionary(x => x.id);
            var vs = w.segs.ToDictionary(x => x.id);
            var rnd = new Random(11);
            int n = 0;
            foreach (var o in w.obstacles)
            {
                if (!map.TryGetValue(o.seg, out var s) || !vs.TryGetValue(o.seg, out var v)) continue;
                var g = Child(parent, $"{o.type}_{o.seg}_{o.s:F1}");
                var (p, dir, left) = OnPath(s, v, o.s);
                var rot = Quaternion.LookRotation(dir);
                switch (o.type)
                {
                    case "narrow":
                        {
                            float gap = o.value / 100f, boxW = Mathf.Max(0.2f, (v.w - gap) / 2);
                            float len = Mathf.Max(0.6f, o.s_end - o.s);
                            var (pm, dm, lm) = OnPath(s, v, o.s + len / 2);
                            foreach (int side in new[] { 1, -1 })
                            {
                                var c = pm + lm * side * (gap / 2 + boxW / 2) + Vector3.up * 0.25f;
                                Prim(g, PrimitiveType.Cube, "Planter", c, Vector3.zero, new Vector3(boxW, 0.5f, len), "Stone").transform.rotation = Quaternion.LookRotation(dm);
                            }
                            break;
                        }
                    case "gap":
                        {
                            bool cross = o.dir != "parallel";
                            var size = cross ? new Vector3(v.w, 0.02f, 0.3f) : new Vector3(0.12f, 0.02f, 1.5f);
                            Prim(g, PrimitiveType.Cube, "Grate", p + Vector3.up * 0.01f, Vector3.zero, size, "Grate").transform.rotation = rot;
                            break;
                        }
                    case "nogo":
                        for (float t = o.s; t <= o.s_end; t += 0.7f)
                        {
                            var (q, _, l2) = OnPath(s, v, t, ((float)rnd.NextDouble() - 0.5f) * v.w * 0.8f);
                            float r = 0.15f + 0.2f * (float)rnd.NextDouble();
                            Prim(g, PrimitiveType.Cube, "Stone", q + Vector3.up * r * 0.3f, new Vector3(rnd.Next(30), rnd.Next(90), rnd.Next(30)), Vector3.one * r, "Basalt");
                        }
                        break;
                    case "broken":
                        Prim(g, PrimitiveType.Cube, "Barrier", p + Vector3.up * 0.5f, Vector3.zero, new Vector3(v.w, 0.15f, 0.1f), "Barrier").transform.rotation = rot;
                        Prim(g, PrimitiveType.Cube, "Hole", p + Vector3.up * 0.005f + dir * 0.6f, Vector3.zero, new Vector3(v.w * 0.8f, 0.01f, 0.9f), "Grate").transform.rotation = rot;
                        break;
                    case "hazard" when o.hazard == "drop":
                        {
                            int side = o.drop_side == "left" ? 1 : -1;
                            for (float t = o.s; t <= o.s_end; t += 2f)
                            {
                                var (q, d2, l2) = OnPath(s, v, t, side * (v.w / 2 + 0.1f));
                                if (o.guard == "rail")
                                {
                                    Prim(g, PrimitiveType.Cube, "Post", q + Vector3.up * 0.5f, Vector3.zero, new Vector3(0.06f, 1.0f, 0.06f), "Sign");
                                    var (q2, _, _) = OnPath(s, v, Mathf.Min(o.s_end, t + 2f), side * (v.w / 2 + 0.1f));
                                    var mid = (q + q2) / 2 + Vector3.up * 1.0f; var d3 = q2 - q;
                                    if (d3.sqrMagnitude > 1e-4f) Prim(g, PrimitiveType.Cube, "Rail", mid, Vector3.zero, new Vector3(0.05f, 0.05f, d3.magnitude), "Sign").transform.rotation = Quaternion.LookRotation(d3);
                                }
                                else if (o.guard == "kerb")
                                    Prim(g, PrimitiveType.Cube, "Kerb", q + Vector3.up * 0.075f, Vector3.zero, new Vector3(0.15f, 0.15f, 2f), "Stone").transform.rotation = Quaternion.LookRotation(d2);
                            }
                            break;
                        }
                    case "temp_block":
                        for (int k = -1; k <= 1; k++)
                            Prim(g, PrimitiveType.Cylinder, "Cone", p + left * (k * v.w / 3) + Vector3.up * 0.35f, Vector3.zero, new Vector3(0.3f, 0.35f, 0.3f), "Barrier");
                        Prim(g, PrimitiveType.Cube, "Board", p + Vector3.up * 0.8f - dir * 0.3f, Vector3.zero, new Vector3(v.w, 0.25f, 0.05f), "Barrier").transform.rotation = rot;
                        break;
                    case "puddle":
                        Prim(g, PrimitiveType.Cylinder, "Puddle", p + Vector3.up * 0.012f, Vector3.zero, new Vector3(Mathf.Min(1.4f, v.w * 0.7f), 0.005f, 0.9f), "Water").transform.rotation = rot;
                        break;
                    case "other":
                        Prim(g, PrimitiveType.Cube, "Lump", p + Vector3.up * 0.03f, Vector3.zero, new Vector3(0.5f, 0.06f, 0.4f), "Bark").transform.rotation = rot;
                        break;
                    default:
                        Object.DestroyImmediate(g);
                        continue;
                }
                n++;
            }
            return n;
        }

        // 3차 시설(가상) 3D: 화장실 건물, 출입구·대여 안내판, 경사로 난간, 연석경사로, 장애인 주차 칸, 벤치
        static int Facilities(GameObject parent, Seg[] segs, VirtualWorld.World w)
        {
            if (w.facilities == null) return 0;
            var map = segs.ToDictionary(x => x.id);
            var vs = w.segs.ToDictionary(x => x.id);
            int n = 0;
            foreach (var f in w.facilities)
            {
                if (!map.TryGetValue(f.seg, out var s) || !vs.TryGetValue(f.seg, out var v)) continue;
                var g = Child(parent, $"{f.type}_{f.seg}_{f.s:F1}");
                var (p, dir, left) = OnPath(s, v, f.s);
                var rot = Quaternion.LookRotation(dir);
                switch (f.type)
                {
                    case "toilet":
                        {
                            // 실제 건물이 있는 화장실(시설 목록에서 건물 안)은 가상 상자를 세우지 않고 표지만 둔다
                            if (!f.on_building)
                            {
                                var (q, _, _) = OnPath(s, v, f.s, v.w / 2 + 2.2f);
                                Prim(g, PrimitiveType.Cube, "Toilet", q + Vector3.up * 1.35f, Vector3.zero, new Vector3(3f, 2.7f, 2.5f), "Concrete").transform.rotation = rot;
                            }
                            Sign(g, "Sign", OnPath(s, v, f.s, v.w / 2 + 0.4f).pos, f.stall == "yes" ? "Sign" : "Grate");
                            break;
                        }
                    case "entrance":
                        Sign(g, "Sign", OnPath(s, v, f.s, v.w / 2 + 0.4f).pos, f.sill_mm >= 100 ? "Barrier" : "Sign", 1.4f);
                        break;
                    case "service":
                        Sign(g, "Sign", OnPath(s, v, f.s, -(v.w / 2 + 0.4f)).pos, "Sign", 2.0f);
                        break;
                    case "ramp":
                        if (f.s1 > f.s0)
                            foreach (int side in new[] { 1, -1 })
                                for (float t = f.s0; t < f.s1; t += 1f)
                                {
                                    var (a, _, _) = OnPath(s, v, t, side * (v.w / 2 + 0.05f));
                                    var (b2, _, _) = OnPath(s, v, Mathf.Min(f.s1, t + 1f), side * (v.w / 2 + 0.05f));
                                    a.y = VirtualWorld.ProfileHeight(v, t) + 0.05f; b2.y = VirtualWorld.ProfileHeight(v, Mathf.Min(f.s1, t + 1f)) + 0.05f;
                                    Prim(g, PrimitiveType.Cube, "Post", a + Vector3.up * 0.45f, Vector3.zero, new Vector3(0.05f, 0.9f, 0.05f), "Sign");
                                    var d3 = b2 - a;
                                    Prim(g, PrimitiveType.Cube, "Rail", (a + b2) / 2 + Vector3.up * 0.85f, Vector3.zero, new Vector3(0.05f, 0.05f, d3.magnitude), "Sign").transform.rotation = Quaternion.LookRotation(d3);
                                }
                        else
                            Prim(g, PrimitiveType.Cube, "Wedge", p + Vector3.up * 0.05f, new Vector3(-5, 0, 0), new Vector3(1.2f, 0.1f, 1.2f), "Concrete").transform.rotation = rot * Quaternion.Euler(-5, 0, 0);
                        break;
                    case "curb_ramp":
                        Prim(g, PrimitiveType.Cube, "CurbRamp", p + Vector3.up * 0.04f, Vector3.zero, new Vector3(Mathf.Max(0.9f, f.w_cm / 100f), 0.05f, 1.0f), "Curb").transform.rotation = rot * Quaternion.Euler(-f.slope, 0, 0);
                        break;
                    case "parking":
                        {
                            var at = new Vector3(f.x, groundFn(f.x, f.z) + 0.03f, f.z);
                            Prim(g, PrimitiveType.Cube, "Stall", at, Vector3.zero, new Vector3(f.w_cm / 100f, 0.02f, f.l_cm / 100f), "Sign").transform.rotation = rot;
                            break;
                        }
                    case "bench":
                        {
                            var (q, _, _) = OnPath(s, v, f.s, v.w / 2 + 0.7f);
                            var bg = Child(g, "Bench"); bg.transform.SetPositionAndRotation(q, rot);
                            Prim(bg, PrimitiveType.Cube, "Seat", new Vector3(0, 0.45f, 0), Vector3.zero, new Vector3(0.45f, 0.06f, 1.6f), "Wood");
                            Prim(bg, PrimitiveType.Cube, "Back", new Vector3(0.22f, 0.75f, 0), Vector3.zero, new Vector3(0.05f, 0.5f, 1.6f), "Wood");
                            foreach (float z in new[] { -0.7f, 0.7f }) Prim(bg, PrimitiveType.Cube, "Leg", new Vector3(0, 0.22f, z), Vector3.zero, new Vector3(0.4f, 0.44f, 0.06f), "Bark");
                            break;
                        }
                    default:
                        Object.DestroyImmediate(g);
                        continue;
                }
                n++;
            }
            return n;
        }

        // 비닐하우스: 반원 지붕 띠 세 줄(반투명 흰색)
        static void Greenhouse(GameObject parent, Bld b, int i)
        {
            var g = Place(parent, $"Greenhouse_{i}", b);
            int bays = Mathf.Clamp(Mathf.RoundToInt(b.d / 7f), 1, 6);
            float bayW = b.d / bays, h = Mathf.Min(3.2f, bayW * 0.45f);
            var mb = new MB();
            const int n = 10;
            for (int k = 0; k < bays; k++)
            {
                float z0 = -b.d / 2 + k * bayW;
                int prevA = -1, prevB = -1;
                for (int j = 0; j <= n; j++)
                {
                    float a = Mathf.PI * j / n, z = z0 + bayW / 2 - Mathf.Cos(a) * bayW / 2, y = Mathf.Sin(a) * h;
                    int ia = mb.V(new Vector3(-b.w / 2, y, z), new Vector2(0, j / (float)n)), ib = mb.V(new Vector3(b.w / 2, y, z), new Vector2(1, j / (float)n));
                    if (prevA >= 0) { var up = new Vector3(0, Mathf.Sin(a), -Mathf.Cos(a)); mb.T(prevA, ia, ib, up); mb.T(prevA, ib, prevB, up); }
                    prevA = ia; prevB = ib;
                }
            }
            MeshObj(g, "Arches", mb.Build($"Greenhouse_{i}"), "Glass");
        }

        // 돌담: 선을 따라 높이 h, 두께 t인 벽(밑은 땅 높이를 따라감) ------------------------------------
        static int Walls(GameObject parent, VirtualWorld.Wall[] walls)
        {
            if (walls == null) return 0;
            var mb = new MB();
            int count = 0;
            foreach (var w in walls)
            {
                var pts = Pts(w.p);
                for (int k = 0; k + 1 < pts.Count; k++)
                {
                    var a = pts[k]; var b = pts[k + 1];
                    var d = b - a; if (d.sqrMagnitude < 1e-6f) continue;
                    var side = new Vector3(-d.z, 0, d.x).normalized * (w.t / 2);
                    float ya = groundFn(a.x, a.z) - 0.1f, yb = groundFn(b.x, b.z) - 0.1f, top = w.h + 0.1f;
                    var q = new[] { a + side, b + side, b - side, a - side };
                    var lo = new[] { ya, yb, yb, ya };
                    var v = new int[8];
                    for (int c = 0; c < 4; c++) { v[c] = mb.V(new Vector3(q[c].x, lo[c], q[c].z), new Vector2(q[c].x / 2f, lo[c] / 2f)); v[c + 4] = mb.V(new Vector3(q[c].x, lo[c] + top, q[c].z), new Vector2(q[c].x / 2f, (lo[c] + top) / 2f)); }
                    // 옆 두 면, 끝 두 면, 윗면
                    mb.T(v[0], v[1], v[5], side); mb.T(v[0], v[5], v[4], side);
                    mb.T(v[2], v[3], v[7], -side); mb.T(v[2], v[7], v[6], -side);
                    mb.T(v[3], v[0], v[4], -d); mb.T(v[3], v[4], v[7], -d);
                    mb.T(v[1], v[2], v[6], d); mb.T(v[1], v[6], v[5], d);
                    mb.T(v[4], v[5], v[6], Vector3.up); mb.T(v[4], v[6], v[7], Vector3.up);
                }
                count++;
                if (mb.v.Count > 60000) { MeshObj(parent, $"Walls_{count}", mb.Build($"Walls_{count}"), "Basalt"); mb = new MB(); }
            }
            if (mb.v.Count > 0) MeshObj(parent, "Walls_last", mb.Build("Walls_last"), "Basalt");
            return count;
        }

        // 울타리: 2 m마다 기둥 + 가로대 두 줄
        static void Fences(GameObject parent, VirtualWorld.Fence[] fences)
        {
            if (fences == null) return;
            var mb = new MB();
            void Box(Vector3 c, Vector3 size, Quaternion rot)
            {
                var corners = new Vector3[8];
                for (int k = 0; k < 8; k++)
                    corners[k] = c + rot * Vector3.Scale(size / 2, new Vector3((k & 1) == 0 ? -1 : 1, (k & 2) == 0 ? -1 : 1, (k & 4) == 0 ? -1 : 1));
                var vi = corners.Select(p => mb.V(p, new Vector2(p.x, p.y))).ToArray();
                int[][] faces = { new[] { 0, 1, 3, 2 }, new[] { 4, 6, 7, 5 }, new[] { 0, 4, 5, 1 }, new[] { 2, 3, 7, 6 }, new[] { 0, 2, 6, 4 }, new[] { 1, 5, 7, 3 } };
                foreach (var f in faces)
                {
                    var n = Vector3.Cross(corners[f[1]] - corners[f[0]], corners[f[2]] - corners[f[0]]);
                    var outward = (corners[f[0]] + corners[f[2]]) / 2 - c;
                    mb.T(vi[f[0]], vi[f[1]], vi[f[2]], outward); mb.T(vi[f[0]], vi[f[2]], vi[f[3]], outward);
                }
            }
            foreach (var f in fences)
            {
                var pts = Pts(f.p);
                float acc = 0;
                for (int k = 0; k + 1 < pts.Count; k++)
                {
                    var a = pts[k]; var b = pts[k + 1]; var d = b - a; float L = d.magnitude; if (L < 1e-4f) continue;
                    var rot = Quaternion.LookRotation(d / L);
                    var mid = (a + b) / 2; float gy = groundFn(mid.x, mid.z);
                    foreach (float hy in new[] { 0.5f, 1.2f }) Box(mid + Vector3.up * (gy + hy), new Vector3(0.05f, 0.08f, L), rot);
                    for (float t = (2 - acc % 2) % 2; t <= L; t += 2)
                    {
                        var p = a + d / L * t; float py = groundFn(p.x, p.z);
                        Box(p + Vector3.up * (py + f.h / 2), new Vector3(0.1f, f.h, 0.1f), rot);
                    }
                    acc += L;
                }
            }
            if (mb.v.Count > 0) MeshObj(parent, "Fences", mb.Build("Fences"), "Wood");
        }

        // 연못: 물높이의 평평한 면(가운데점에서 부채꼴로)
        static void Ponds(GameObject parent, VirtualWorld.Water[] water)
        {
            if (water == null) return;
            foreach (var w in water)
            {
                var pts = Pts(w.ring);
                var mb = new MB();
                var c = Vector3.zero; foreach (var p in pts) c += p; c /= pts.Count; c.y = w.level;
                int ci = mb.V(c, new Vector2(c.x / 5f, c.z / 5f));
                for (int k = 0; k < pts.Count; k++)
                {
                    var p0 = pts[k]; var p1 = pts[(k + 1) % pts.Count]; p0.y = p1.y = w.level;
                    mb.T(ci, mb.V(p0, new Vector2(p0.x / 5f, p0.z / 5f)), mb.V(p1, new Vector2(p1.x / 5f, p1.z / 5f)), Vector3.up);
                }
                MeshObj(parent, "Pond", mb.Build("Pond"), "Water");
            }
        }

        // 가상 땅: 설계도 높이 격자 그대로 + 항공사진(사진 범위는 평면 땅과 같음) -------------------------
        static void VirtualGround(GameObject parent, float size, VirtualWorld.World w)
        {
            var texPath = Dir + "/Data/aerial.jpg";
            var aerial = Mat("Aerial");
            aerial.SetTexture("_BaseMap", AssetDatabase.LoadAssetAtPath<Texture2D>(texPath));
            var t = w.terrain;
            float half = size / 2, minH = t.h.Min();
            var mb = new MB();
            for (int iz = 0; iz < t.n; iz++)
                for (int ix = 0; ix < t.n; ix++)
                {
                    float x = t.origin + ix * t.cell, z = t.origin + iz * t.cell;
                    mb.V(new Vector3(x, t.h[iz * t.n + ix], z), new Vector2((x + half) / size, (z + half) / size));
                }
            for (int iz = 0; iz + 1 < t.n; iz++)
                for (int ix = 0; ix + 1 < t.n; ix++)
                {
                    int a = iz * t.n + ix, b = a + 1, c = a + t.n + 1, d = a + t.n;
                    mb.T(a, b, c, Vector3.up); mb.T(a, c, d, Vector3.up);
                }
            MeshObj(parent, "Terrain", mb.Build("Terrain"), "Aerial");

            var outer = new MB();
            float o = 4000f, y = minH - 0.1f;
            int oa = outer.V(new Vector3(-o, y, -o), Vector2.zero), ob = outer.V(new Vector3(o, y, -o), Vector2.zero);
            int oc = outer.V(new Vector3(o, y, o), Vector2.zero), od = outer.V(new Vector3(-o, y, o), Vector2.zero);
            outer.T(oa, ob, oc, Vector3.up); outer.T(oa, oc, od, Vector3.up);
            MeshObj(parent, "Outer", outer.Build("Outer"), "Field");
        }

        // 가상 길: 높이 단면을 따라 오르내리고, 좌우 기울기 토막에서 옆으로 기운 띠.
        // 노면 토막·계단마다 따로 그물(재질 Surf_<재질>, 계단은 StepStone)과 MeshCollider. 반환: 토막 수
        static int VirtualPath(GameObject paths, Seg s, VirtualWorld.VSeg v, ILookup<int, VirtualWorld.VSeg> byNode)
        {
            var seg = Child(paths, $"Seg_{s.id}");
            var cuts = new List<float> { 0, v.len };
            foreach (var x in v.surf) { cuts.Add(x.s0); cuts.Add(x.s1); }
            foreach (var x in v.steps) { cuts.Add(x.s0); cuts.Add(x.s1); }
            cuts = cuts.Select(c => Mathf.Clamp(c, 0, v.len)).Distinct().OrderBy(c => c).ToList();
            var vs = VirtualWorld.VertexS(s.p, v.len);
            int pieces = 0;
            for (int k = 0; k + 1 < cuts.Count; k++)
            {
                float a = cuts[k], b = cuts[k + 1];
                if (b - a < 1e-4f) continue;
                float mid = (a + b) / 2;
                bool stairs = VirtualWorld.InSteps(v, mid);
                var sf = v.surf.FirstOrDefault(x => x.s0 <= mid && mid <= x.s1);
                string mat = stairs ? "StepStone" : $"Surf_{sf?.material ?? "other"}";
                var mesh = VirtualRibbon(s, v, a, b, vs, $"Seg_{s.id}_{k}");
                var g = MeshObj(seg, $"{(stairs ? "Steps" : "Surf")}_{k}_{(stairs ? "stairs" : sf?.material)}", mesh, mat);
                g.AddComponent<MeshCollider>().sharedMesh = mesh;
                pieces++;
            }
            // 양 끝 둥근 판(이웃 구간과 만나는 곳의 빈틈 메우기, 충돌체 없음). 계단 끝에는 두지 않는다(계단 위에 노면 판이 보임).
            // 가운데는 마디 높이 + 4 cm, 반지름 r 자리는 그 마디에 모인 길이 r 안에서 가장 많이 내려가는 만큼 낮춘다
            // (경사진 끝에서 판이 뜨지 않게, 고리 세 겹). 오르는 쪽은 길 아래로 숨는다.
            foreach (float e in new[] { 0f, v.len })
            {
                if (VirtualWorld.InSteps(v, e, 0.01f)) continue;
                int node = e == 0 ? v.a : v.b;
                var c = VirtualWorld.PointAt(s.p, v.len, e).pos;
                c.y = VirtualWorld.ProfileHeight(v, e) + 0.04f;
                var mb = new MB();
                int ci = mb.V(c, new Vector2(c.x / 3f, c.z / 3f));
                const int n = 12, rings = 3;
                var prev = new int[n];
                for (int k = 1; k <= rings; k++)
                {
                    float r = v.w / 2 * k / rings, y = c.y - NodeDrop(byNode[node], node, r);
                    var cur = new int[n];
                    for (int i = 0; i < n; i++)
                    {
                        float ang = i * Mathf.PI * 2 / n;
                        var q = new Vector3(c.x + Mathf.Cos(ang) * r, y, c.z + Mathf.Sin(ang) * r);
                        cur[i] = mb.V(q, new Vector2(q.x / 3f, q.z / 3f));
                    }
                    for (int i = 0; i < n; i++)
                    {
                        int i2 = (i + 1) % n;
                        if (k == 1) mb.T(ci, cur[i], cur[i2], Vector3.up);
                        else { mb.T(prev[i], cur[i], cur[i2], Vector3.up); mb.T(prev[i], cur[i2], prev[i2], Vector3.up); }
                    }
                    prev = cur;
                }
                var sf = v.surf.FirstOrDefault(x => x.s0 <= e && e <= x.s1);
                MeshObj(seg, e == 0 ? "JointA" : "JointB", mb.Build($"Joint_{s.id}_{(e == 0 ? "a" : "b")}"), $"Surf_{sf?.material ?? "other"}");
            }
            return pieces;
        }

        // 마디 node에서 t m 안쪽까지, 그 마디에 모인 길 중 가장 많이 내려가는 높이(앞뒤 단면 + 좌우 기울기로 낮아진 가장자리)
        static float NodeDrop(IEnumerable<VirtualWorld.VSeg> segsAtNode, int node, float t)
        {
            float drop = 0;
            foreach (var g in segsAtNode)
                foreach (float e in new[] { 0f, g.len })
                {
                    if ((e == 0 ? g.a : g.b) != node) continue;
                    float hn = VirtualWorld.ProfileHeight(g, e), lo = hn, span = Mathf.Min(t, g.len);
                    for (float d = 0; d <= span + 1e-4f; d += 0.05f)
                        lo = Mathf.Min(lo, VirtualWorld.ProfileHeight(g, e == 0 ? d : g.len - d));
                    float side = Mathf.Min(t, g.w / 2) * Mathf.Tan(VirtualWorld.CrossAt(g, e).deg * Mathf.Deg2Rad);
                    drop = Mathf.Max(drop, hn - lo + side);
                }
            return drop;
        }

        // [a, b] 토막의 띠. 줄(가로 단면)은 높이 단면의 점(같은 s 두 번 = 턱·계단 단), 선 꼭짓점, 좌우 토막 끝에 둔다.
        static Mesh VirtualRibbon(Seg s, VirtualWorld.VSeg v, float a, float b, float[] vertexS, string name)
        {
            // 줄 방향은 그 자리 선분 방향(곧은 토막 안의 줄은 모두 나란해 가운데선 높이가 정확).
            // 꼭짓점에는 들어오는 방향(-1)과 나가는 방향(+1) 두 줄을 같은 자리에 둔다.
            var rows = new List<(float s, float h, int side)>();
            for (int i = 0; i + 1 < v.prof.Length; i += 2)
                if (v.prof[i] >= a - 1e-4f && v.prof[i] <= b + 1e-4f) rows.Add((v.prof[i], v.prof[i + 1], 0));
            var extra = new List<float> { a, b };
            foreach (var c in v.cross) { if (c.s0 > a && c.s0 < b) extra.Add(c.s0); if (c.s1 > a && c.s1 < b) extra.Add(c.s1); }
            foreach (var x in extra)
                if (!rows.Any(r => Mathf.Abs(r.s - x) < 1e-3f)) rows.Add((x, VirtualWorld.ProfileHeight(v, x), 0));
            foreach (var x in vertexS.Where(x => x > a + 1e-3f && x < b - 1e-3f))
            {
                rows.RemoveAll(r => Mathf.Abs(r.s - x) < 1e-3f && r.side == 0);
                float hx = VirtualWorld.ProfileHeight(v, x);
                rows.Add((x, hx, -1)); rows.Add((x, hx, 1));
            }
            rows = rows.Select((r, i) => (r, i)).OrderBy(t => t.r.s).ThenBy(t => t.r.side).ThenBy(t => t.i).Select(t => t.r).ToList();

            var mb = new MB();
            int pl = -1, pr = -1;
            float ps = 0, ph = 0;
            Vector3 pdir = Vector3.forward;
            foreach (var (sx, h, sideRow) in rows)
            {
                var pos = VirtualWorld.PointAt(s.p, v.len, sx).pos;
                var dir = VirtualWorld.PointAt(s.p, v.len, sideRow > 0 ? Mathf.Min(v.len, sx + 1e-3f) : sideRow < 0 ? Mathf.Max(0, sx - 1e-3f) : sx).dir;
                var left = new Vector3(-dir.z, 0, dir.x);
                var (deg, lowLeft) = VirtualWorld.CrossAt(v, sx);
                float tilt = v.w / 2 * Mathf.Tan(deg * Mathf.Deg2Rad), y = h + 0.05f;
                var L = pos + left * (v.w / 2); L.y = y + (lowLeft ? -tilt : tilt);
                var R = pos - left * (v.w / 2); R.y = y + (lowLeft ? tilt : -tilt);
                int li = mb.V(L, new Vector2(L.x / 3f, L.z / 3f)), ri = mb.V(R, new Vector2(R.x / 3f, R.z / 3f));
                if (pl >= 0)
                {
                    // 앞면 법선: 오르막 면의 위쪽(높이 차만 있으면 다가오는 쪽)
                    var hint = Vector3.up * (sx - ps) - pdir * (h - ph);
                    if (hint.sqrMagnitude < 1e-10f) hint = Vector3.up; // 꼭짓점의 두 줄 사이(꺾인 곳 메우기)
                    mb.T(pl, li, ri, hint); mb.T(pl, ri, pr, hint);
                }
                pl = li; pr = ri; ps = sx; ph = h; pdir = dir;
            }
            return mb.Build(name);
        }

        // 가상 세계 확인용 시점: 가장 가파른 길, 18~22 mm 턱, 구간 190 계단, 재질이 바뀌는 곳
        static void VirtualViews(GameObject root, Seg[] segs, VirtualWorld.World w)
        {
            var map = segs.ToDictionary(x => x.id);
            void Look(string name, Seg s, VirtualWorld.VSeg v, float at, float back, float up)
            {
                var (pos, _) = VirtualWorld.PointAt(s.p, v.len, at);
                var dir = VirtualWorld.SmoothDir(s.p, v.len, at);
                var side = new Vector3(-dir.z, 0, dir.x);
                float h = VirtualWorld.ProfileHeight(v, at);
                // 길 높이 기준으로 직접 놓는다(View는 땅 높이를 더하므로 위치를 다시 정함)
                var g = View(root, name, pos, pos).transform;
                g.position = pos - dir * back + side * (back * 0.4f) + Vector3.up * (h + up);
                g.LookAt(pos + Vector3.up * (h + 0.2f));
            }
            VirtualWorld.VSeg Find(Func<VirtualWorld.VSeg, bool> f) => w.segs.FirstOrDefault(v => map.ContainsKey(v.id) && f(v));

            var steep = w.segs.Where(v => map.ContainsKey(v.id) && v.steps.Length == 0 && v.len > 8)
                .OrderByDescending(v => Mathf.Abs(VirtualWorld.ProfileHeight(v, v.len) - VirtualWorld.ProfileHeight(v, 0)) / v.len).FirstOrDefault();
            if (steep != null) Look("ViewSlope", map[steep.id], steep, steep.len / 2, 12, 3);
            var bump = Find(v => !map[v.id].road && v.bumps.Any(b => b.mm >= 18 && b.mm <= 22)) ?? Find(v => v.bumps.Any(b => b.mm >= 18 && b.mm <= 22));
            if (bump != null) Look("ViewBump", map[bump.id], bump, bump.bumps.First(b => b.mm >= 18 && b.mm <= 22).s, 2.5f, 0.9f);
            var st = Find(v => v.id == 190) ?? Find(v => v.steps.Length > 0);
            if (st != null) Look("ViewSteps", map[st.id], st, (st.steps[0].s0 + st.steps[0].s1) / 2, 7, 3);
            var sf = Find(v => v.surf.Length >= 2 && v.surf[0].material != v.surf[1].material && v.steps.Length == 0);
            if (sf != null) Look("ViewSurface", map[sf.id], sf, sf.surf[0].s1, 6, 2.5f);
            // 가운데 모래 마당(항공사진에서 고른 기와집)과 돌담·울타리가 보이는 시점
            View(root, "ViewCenter", new Vector3(-25, 45, -75), new Vector3(16, 0, -18));
            // 2·3차 항목 확인 시점
            void LookAtItem(string name, int segId, float at, float back, float up)
            {
                var v = w.segs.FirstOrDefault(x => x.id == segId);
                if (v != null && map.ContainsKey(segId)) Look(name, map[segId], v, at, back, up);
            }
            var nar = w.obstacles?.FirstOrDefault(o => o.type == "narrow");
            if (nar != null) LookAtItem("ViewNarrow", nar.seg, nar.s, 5, 1.8f);
            var drop = w.obstacles?.FirstOrDefault(o => o.type == "hazard" && o.hazard == "drop" && o.guard == "rail");
            if (drop != null) LookAtItem("ViewDrop", drop.seg, (drop.s + drop.s_end) / 2, 6, 2.5f);
            var wc = w.facilities?.FirstOrDefault(f => f.type == "toilet");
            if (wc != null) LookAtItem("ViewToilet", wc.seg, wc.s, 7, 3f);
            var tb = w.obstacles?.FirstOrDefault(o => o.type == "temp_block");
            if (tb != null) LookAtItem("ViewWorks", tb.seg, tb.s, 5, 1.8f);
            View(root, "ViewZoo", new Vector3(150, 30, 5), new Vector3(190, 0, 50));
        }

        // 샘플 장면을 복사해 카메라·해·후처리를 그대로 쓴다
        static void OpenScene()
        {
            EditorSceneManager.SaveOpenScenes();
            if (!File.Exists(ScenePath)) AssetDatabase.CopyAsset("Assets/Scenes/SampleScene.unity", ScenePath);
            if (EditorSceneManager.GetActiveScene().path != ScenePath) EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
            foreach (var name in new[] { "Village", "Minsokchon", "Airplane" })
            {
                var old = GameObject.Find(name);
                if (old) Object.DestroyImmediate(old);
            }
        }

        // 땅: 항공사진 한 장(사진 크기 그대로) + 바깥은 넓은 풀빛 평면 --------------------------
        static void Ground(GameObject parent, float size)
        {
            var texPath = Dir + "/Data/aerial.jpg";
            var imp = (TextureImporter)AssetImporter.GetAtPath(texPath);
            if (imp.maxTextureSize != 4096 || imp.anisoLevel != 9 || imp.textureCompression != TextureImporterCompression.CompressedHQ)
            {
                imp.maxTextureSize = 4096;
                imp.anisoLevel = 9;
                imp.textureCompression = TextureImporterCompression.CompressedHQ;
                imp.wrapMode = TextureWrapMode.Clamp;
                imp.SaveAndReimport();
            }
            var aerial = Mat("Aerial");
            aerial.SetTexture("_BaseMap", AssetDatabase.LoadAssetAtPath<Texture2D>(texPath));
            float h = size / 2;
            var mb = new MB();
            int a = mb.V(new Vector3(-h, 0, -h), new Vector2(0, 0)), b = mb.V(new Vector3(h, 0, -h), new Vector2(1, 0));
            int c = mb.V(new Vector3(h, 0, h), new Vector2(1, 1)), d = mb.V(new Vector3(-h, 0, h), new Vector2(0, 1));
            mb.T(a, b, c, Vector3.up); mb.T(a, c, d, Vector3.up);
            MeshObj(parent, "Aerial", mb.Build("Aerial"), "Aerial");

            var outer = new MB();
            float o = 4000f;
            a = outer.V(new Vector3(-o, -0.08f, -o), Vector2.zero); b = outer.V(new Vector3(o, -0.08f, -o), Vector2.zero);
            c = outer.V(new Vector3(o, -0.08f, o), Vector2.zero); d = outer.V(new Vector3(-o, -0.08f, o), Vector2.zero);
            outer.T(a, b, c, Vector3.up); outer.T(a, c, d, Vector3.up);
            MeshObj(parent, "Outer", outer.Build("Outer"), "Field");
        }

        // 길: 폭 w인 띠(꺾이는 곳은 맞춤, 꼭짓점마다 둥근 판) -----------------------------------
        static Mesh Ribbon(List<Vector3> p, float w, float y)
        {
            var mb = new MB();
            Func<Vector3, Vector2> uvf = q => new Vector2(q.x / 3f, q.z / 3f);
            int prevL = -1, prevR = -1;
            for (int i = 0; i < p.Count; i++)
            {
                Vector3 din = i > 0 ? (p[i] - p[i - 1]).normalized : Vector3.zero;
                Vector3 dout = i < p.Count - 1 ? (p[i + 1] - p[i]).normalized : Vector3.zero;
                var t = (din + dout).sqrMagnitude > 1e-6f ? (din + dout).normalized : (dout != Vector3.zero ? dout : din);
                var left = new Vector3(-t.z, 0, t.x);
                var refDir = din != Vector3.zero ? din : dout;
                float miter = 1f / Mathf.Max(0.5f, Vector3.Dot(left, new Vector3(-refDir.z, 0, refDir.x)));
                var c = new Vector3(p[i].x, y, p[i].z);
                var L = c + left * (w / 2 * miter);
                var R = c - left * (w / 2 * miter);
                int li = mb.V(L, uvf(L)), ri = mb.V(R, uvf(R));
                if (prevL >= 0) { mb.T(prevL, li, ri, Vector3.up); mb.T(prevL, ri, prevR, Vector3.up); }
                prevL = li; prevR = ri;
                // 둥근 판: 꺾인 곳과 끝의 빈틈을 메운다
                int ci = mb.V(c, uvf(c));
                const int n = 12;
                int first = -1, last = -1;
                for (int k = 0; k <= n; k++)
                {
                    float ang = k * Mathf.PI * 2 / n;
                    var q = c + new Vector3(Mathf.Cos(ang), 0, Mathf.Sin(ang)) * (w / 2);
                    int qi = k < n ? mb.V(q, uvf(q)) : first;
                    if (k == 0) first = qi; else mb.T(ci, last, qi, Vector3.up);
                    last = qi;
                }
            }
            return mb.Build("Path");
        }

        // 계단: 선을 따라 0.35 m마다 디딤돌 ---------------------------------------------------
        static void Stairs(GameObject parent, List<Vector3> p)
        {
            var g = Child(parent, "Stairs");
            for (int i = 0; i < p.Count - 1; i++)
            {
                var d = p[i + 1] - p[i];
                int n = Mathf.Max(1, Mathf.RoundToInt(d.magnitude / 0.35f));
                var rot = Quaternion.LookRotation(d.normalized);
                for (int k = 0; k < n; k++)
                {
                    var c = p[i] + d * ((k + 0.5f) / n);
                    var s = Prim(g, PrimitiveType.Cube, "Step", c + Vector3.up * 0.09f, Vector3.zero, new Vector3(2.0f, 0.18f, 0.24f), "StepStone");
                    s.transform.rotation = rot;
                }
            }
        }

        // 초가: 현무암 벽 + 나무 앞면 + 둥근 초가지붕(줄 격자) -----------------------------------
        static void Thatch(GameObject parent, Bld b, int i)
        {
            var g = Place(parent, $"Thatch_{i}", b);
            float bw = Mathf.Max(b.w - 0.9f, 1.4f), bd = Mathf.Max(b.d - 0.9f, 1.2f), wallH = 2.0f;
            MeshObj(g, "Wall", BoxMesh($"ThatchWall_{i}", bw, wallH, bd), "Basalt");
            Prim(g, PrimitiveType.Cube, "Front", new Vector3(0, 0.9f, b.front * (bd / 2 + 0.03f)), Vector3.zero, new Vector3(bw * 0.55f, 1.7f, 0.06f), "Wood");
            float W = b.w + 0.3f, D = b.d + 0.3f, h = Mathf.Clamp(b.d * 0.3f, 1.1f, 1.9f);
            var roof = MeshObj(g, "Roof", Roof($"ThatchRoof_{i}", W, D, 0.35f, (u, v) =>
            {
                float s = Mathf.Pow(Mathf.Pow(Mathf.Abs(u), 4) + Mathf.Pow(Mathf.Abs(v), 4), 0.25f);
                float k = s > 1 ? 1 / s : 1, sr = Mathf.Min(s, 1);
                float x = u * k * W / 2, z = v * k * D / 2;
                float m = Mathf.Clamp01(Mathf.Min(D / 2 - Mathf.Abs(z), W / 2 - Mathf.Abs(x)) / (D / 2));
                m = Mathf.Min(m, 1.6f * (1 - sr));
                return new Vector3(x, h * Mathf.Pow(1 - (1 - m) * (1 - m), 0.8f), z);
            }), "Thatch");
            roof.transform.localPosition = new Vector3(0, wallH - 0.1f, 0);
        }

        // 기와집: 돌 기단 + 회벽 + 나무 문 + 처마 끝이 들린 우진각 지붕 --------------------------------
        static void Tile(GameObject parent, Bld b, int i)
        {
            var g = Place(parent, $"Tile_{i}", b);
            float bw = Mathf.Max(b.w - 1.8f, 1.5f), bd = Mathf.Max(b.d - 1.8f, 1.2f), baseH = 0.5f, wallH = 2.6f;
            MeshObj(g, "Base", BoxMesh($"TileBase_{i}", bw + 0.8f, baseH, bd + 0.8f), "Stone");
            MeshObj(g, "Wall", BoxMesh($"TileWall_{i}", bw, wallH, bd), "Plaster").transform.localPosition = new Vector3(0, baseH, 0);
            Prim(g, PrimitiveType.Cube, "Doors", new Vector3(0, baseH + 1.1f, b.front * (bd / 2 + 0.03f)), Vector3.zero, new Vector3(bw * 0.7f, 2.2f, 0.06f), "Wood");
            float W = b.w, D = b.d, hr = Mathf.Clamp(D * 0.3f, 1.4f, 3.2f);
            var roof = MeshObj(g, "Roof", Roof($"TileRoof_{i}", W, D, 0.3f, (u, v) =>
            {
                float x = u * W / 2, z = v * D / 2;
                float e = Mathf.Clamp01(Mathf.Min(D / 2 - Mathf.Abs(z), W / 2 - Mathf.Abs(x)) / (D / 2));
                return new Vector3(x, hr * Mathf.Pow(e, 1.3f) + 0.45f * Mathf.Pow(Mathf.Abs(u * v), 6), z);
            }), "Giwa");
            roof.transform.localPosition = new Vector3(0, baseH + wallH - 0.1f, 0);
            float ridge = Mathf.Max(W - D, 0.4f);
            Prim(g, PrimitiveType.Cube, "Ridge", new Vector3(0, baseH + wallH - 0.1f + hr + 0.05f, 0), Vector3.zero, new Vector3(ridge, 0.3f, 0.35f), "Giwa");
        }

        // 현대 건물: 윤곽을 층수 x 3.4 m로 올리고, 지붕은 항공사진 색 ------------------------------------
        static void Modern(GameObject parent, Bld b, int i)
        {
            float h = Mathf.Max(b.floors, 1) * 3.4f;
            var ring = Pts(b.ring);
            var mb = new MB();
            var cen = Vector3.zero;
            foreach (var q in ring) cen += q;
            cen /= ring.Count;
            for (int k = 0; k < ring.Count; k++)
            {
                var p0 = ring[k];
                var p1 = ring[(k + 1) % ring.Count];
                var e = p1 - p0;
                var outN = new Vector3(e.z, 0, -e.x); // 반시계 윤곽의 바깥쪽
                float u0 = 0, u1 = e.magnitude / 4f;
                int a0 = mb.V(p0, new Vector2(u0, 0)), a1 = mb.V(p1, new Vector2(u1, 0));
                int b0 = mb.V(p0 + Vector3.up * h, new Vector2(u0, h / 4f)), b1 = mb.V(p1 + Vector3.up * h, new Vector2(u1, h / 4f));
                mb.T(a0, b0, b1, outN); mb.T(a0, b1, a1, outN);
            }
            var walls = mb.Build($"ModernWalls_{i}");
            var top = new MB();
            var idx = new int[ring.Count];
            for (int k = 0; k < ring.Count; k++) idx[k] = top.V(ring[k] + Vector3.up * h, Vector2.zero);
            for (int k = 0; k + 2 < b.tris.Length; k += 3) top.T(idx[b.tris[k]], idx[b.tris[k + 1]], idx[b.tris[k + 2]], Vector3.up);
            var g = Child(parent, $"Modern_{i}" + (string.IsNullOrEmpty(b.name) ? "" : $"_{b.name}"));
            // 경사진 땅에서 뜨지 않게 윤곽 점 중 가장 낮은 땅 높이에 놓는다(높은 쪽은 땅에 조금 묻힘)
            g.transform.position = new Vector3(0, ring.Concat(new[] { cen }).Min(q => groundFn(q.x, q.z)), 0);
            MeshObj(g, "Walls", walls, "Concrete");
            MeshObj(g, "Top", top.Build($"ModernTop_{i}"), RoofMat(b.roof));
        }

        // 바닥이 y = 0인 상자. 무늬는 2 m에 한 번(크기를 키워도 늘어나지 않게)
        static Mesh BoxMesh(string name, float w, float h, float d)
        {
            var mb = new MB();
            float x = w / 2, z = d / 2;
            var faces = new[] {
                (n: Vector3.forward, a: new Vector3(-x, 0, z), r: Vector3.right * w, u: Vector3.up * h),
                (n: Vector3.back, a: new Vector3(x, 0, -z), r: Vector3.left * w, u: Vector3.up * h),
                (n: Vector3.right, a: new Vector3(x, 0, z), r: Vector3.back * d, u: Vector3.up * h),
                (n: Vector3.left, a: new Vector3(-x, 0, -z), r: Vector3.forward * d, u: Vector3.up * h),
                (n: Vector3.up, a: new Vector3(-x, h, -z), r: Vector3.right * w, u: Vector3.forward * d),
            };
            foreach (var f in faces)
            {
                float lu = f.r.magnitude / 2f, lv = f.u.magnitude / 2f;
                int a = mb.V(f.a, new Vector2(0, 0)), b = mb.V(f.a + f.r, new Vector2(lu, 0));
                int c = mb.V(f.a + f.r + f.u, new Vector2(lu, lv)), e = mb.V(f.a + f.u, new Vector2(0, lv));
                mb.T(a, b, c, f.n); mb.T(a, c, e, f.n);
            }
            return mb.Build(name);
        }

        // 지붕 격자: surf(u, v)가 위 면, 밑면은 y = -thick 평면, 가장자리는 띠로 막는다
        static Mesh Roof(string name, float W, float D, float thick, Func<float, float, Vector3> surf)
        {
            const int N = 28, M = 16;
            var mb = new MB();
            var top = new int[N + 1, M + 1];
            var bot = new int[N + 1, M + 1];
            Func<Vector3, Vector2> uvf = q => new Vector2(q.x / 2f, q.z / 2f);
            for (int i = 0; i <= N; i++)
                for (int j = 0; j <= M; j++)
                {
                    var q = surf(-1 + 2f * i / N, -1 + 2f * j / M);
                    top[i, j] = mb.V(q, uvf(q));
                }
            for (int i = 0; i <= N; i++)
                for (int j = 0; j <= M; j++)
                {
                    var q = mb.v[top[i, j]];
                    var qb = new Vector3(q.x, -thick, q.z);
                    bot[i, j] = mb.V(qb, uvf(qb));
                }
            for (int i = 0; i < N; i++)
                for (int j = 0; j < M; j++)
                {
                    mb.T(top[i, j], top[i + 1, j], top[i + 1, j + 1], Vector3.up);
                    mb.T(top[i, j], top[i + 1, j + 1], top[i, j + 1], Vector3.up);
                    mb.T(bot[i, j], bot[i + 1, j], bot[i + 1, j + 1], Vector3.down);
                    mb.T(bot[i, j], bot[i + 1, j + 1], bot[i, j + 1], Vector3.down);
                }
            // 가장자리 띠(따로 꼭짓점을 만들어 모서리를 날카롭게)
            var border = new List<(int, int)>();
            for (int i = 0; i < N; i++) border.Add((i, 0));
            for (int j = 0; j < M; j++) border.Add((N, j));
            for (int i = N; i > 0; i--) border.Add((i, M));
            for (int j = M; j > 0; j--) border.Add((0, j));
            for (int k = 0; k < border.Count; k++)
            {
                var (i0, j0) = border[k];
                var (i1, j1) = border[(k + 1) % border.Count];
                Vector3 t0 = mb.v[top[i0, j0]], t1 = mb.v[top[i1, j1]], b0 = mb.v[bot[i0, j0]], b1 = mb.v[bot[i1, j1]];
                var outN = (t0 + t1) * 0.5f;
                outN.y = 0;
                int a = mb.V(t0, new Vector2(k * 0.1f, 1)), c = mb.V(t1, new Vector2(k * 0.1f + 0.1f, 1));
                int d = mb.V(b0, new Vector2(k * 0.1f, 0)), e = mb.V(b1, new Vector2(k * 0.1f + 0.1f, 0));
                mb.T(a, d, e, outN); mb.T(a, e, c, outN);
            }
            return mb.Build(name);
        }

        // 나무: 80 m 칸마다 재질별로 한 메시에 모은다(수천 그루라 오브젝트를 줄임) ---------------------------
        static int Trees(GameObject parent, float[] t, Random rnd)
        {
            var ico = Icosphere();
            var groups = new Dictionary<(int, int, int), (List<Vector3> v, List<Vector3> n, List<int> tr)>();
            (List<Vector3> v, List<Vector3> n, List<int> tr) G(int gx, int gz, int m)
            {
                if (!groups.TryGetValue((gx, gz, m), out var gr)) groups[(gx, gz, m)] = gr = (new List<Vector3>(), new List<Vector3>(), new List<int>());
                return gr;
            }
            int count = 0;
            for (int i = 0; i + 3 < t.Length; i += 4, count++)
            {
                float x = t[i], z = t[i + 1], r = t[i + 2];
                int shade = (int)t[i + 3];
                int gx = Mathf.FloorToInt(x / TreeTile), gz = Mathf.FloorToInt(z / TreeTile);
                float trunkH = r * 0.7f + R(rnd, 0.3f, 1.2f);
                var scale = new Vector3(r, r * R(rnd, 0.75f, 0.95f), r * R(rnd, 0.9f, 1.1f));
                float gy = groundFn(x, z);
                var c = new Vector3(x, gy + trunkH + scale.y * 0.7f, z);
                var crown = G(gx, gz, shade);
                int baseIdx = crown.v.Count;
                float seed = R(rnd, 0, 100);
                foreach (var p in ico.v)
                {
                    float bump = 0.85f + 0.3f * Mathf.PerlinNoise(p.x * 1.7f + seed, p.z * 1.7f + p.y + seed);
                    var q = Vector3.Scale(p * bump, scale);
                    crown.v.Add(c + q);
                    crown.n.Add(new Vector3(q.x / (scale.x * scale.x), q.y / (scale.y * scale.y), q.z / (scale.z * scale.z)).normalized);
                }
                foreach (int k in ico.t) crown.tr.Add(baseIdx + k);
                // 절반쯤은 옆에 작은 덩어리를 하나 더 붙여 공 모양을 깬다
                if (rnd.NextDouble() < 0.55)
                {
                    float a = R(rnd, 0, Mathf.PI * 2), s2 = R(rnd, 0.55f, 0.75f);
                    var c2 = c + new Vector3(Mathf.Cos(a) * r * 0.55f, R(rnd, -0.2f, 0.35f) * r, Mathf.Sin(a) * r * 0.55f);
                    var sc2 = scale * s2;
                    baseIdx = crown.v.Count;
                    foreach (var p in ico.v)
                    {
                        var q = Vector3.Scale(p, sc2);
                        crown.v.Add(c2 + q);
                        crown.n.Add(new Vector3(q.x / (sc2.x * sc2.x), q.y / (sc2.y * sc2.y), q.z / (sc2.z * sc2.z)).normalized);
                    }
                    foreach (int k in ico.t) crown.tr.Add(baseIdx + k);
                }
                var trunk = G(gx, gz, 3);
                float tr = 0.12f + 0.04f * r, top = trunkH + scale.y * 0.4f;
                baseIdx = trunk.v.Count;
                for (int k = 0; k < 6; k++)
                {
                    float a = k * Mathf.PI / 3;
                    var dir = new Vector3(Mathf.Cos(a), 0, Mathf.Sin(a));
                    trunk.v.Add(new Vector3(x, gy, z) + dir * tr); trunk.n.Add(dir);
                    trunk.v.Add(new Vector3(x, gy + top, z) + dir * tr * 0.7f); trunk.n.Add(dir);
                }
                for (int k = 0; k < 6; k++)
                {
                    int a0 = baseIdx + k * 2, a1 = baseIdx + ((k + 1) % 6) * 2;
                    // 바깥에서 볼 때 시계 방향
                    trunk.tr.AddRange(new[] { a0, a0 + 1, a1 + 1, a0, a1 + 1, a1 });
                }
            }
            string[] matNames = { "Leaf0", "Leaf1", "Leaf2", "Bark" };
            foreach (var kv in groups)
            {
                var (gx, gz, m) = kv.Key;
                var mesh = new Mesh { name = $"Trees_{gx}_{gz}_{matNames[m]}", indexFormat = IndexFormat.UInt32 };
                mesh.SetVertices(kv.Value.v);
                mesh.SetNormals(kv.Value.n);
                mesh.SetTriangles(kv.Value.tr, 0);
                mesh.RecalculateBounds();
                // 줄기 삼각형 방향은 위에서 맞췄으므로 그대로, 수관은 정이십면체 방향 그대로
                MeshObj(parent, mesh.name, Store(mesh), matNames[m]);
            }
            return count;
        }

        // 정이십면체를 한 번 나눈 공(꼭짓점 42개, 삼각형 80개). 바깥을 향하도록 감는다.
        static (List<Vector3> v, List<int> t) Icosphere()
        {
            float p = (1 + Mathf.Sqrt(5)) / 2;
            var v = new List<Vector3> {
                new Vector3(-1, p, 0), new Vector3(1, p, 0), new Vector3(-1, -p, 0), new Vector3(1, -p, 0),
                new Vector3(0, -1, p), new Vector3(0, 1, p), new Vector3(0, -1, -p), new Vector3(0, 1, -p),
                new Vector3(p, 0, -1), new Vector3(p, 0, 1), new Vector3(-p, 0, -1), new Vector3(-p, 0, 1) };
            for (int i = 0; i < v.Count; i++) v[i] = v[i].normalized;
            var f = new List<int> { 0,11,5, 0,5,1, 0,1,7, 0,7,10, 0,10,11, 1,5,9, 5,11,4, 11,10,2, 10,7,6, 7,1,8,
                3,9,4, 3,4,2, 3,2,6, 3,6,8, 3,8,9, 4,9,5, 2,4,11, 6,2,10, 8,6,7, 9,8,1 };
            var mid = new Dictionary<(int, int), int>();
            int Mid(int a, int b)
            {
                var key = a < b ? (a, b) : (b, a);
                if (mid.TryGetValue(key, out int m)) return m;
                v.Add(((v[a] + v[b]) / 2).normalized);
                return mid[key] = v.Count - 1;
            }
            var t = new List<int>();
            for (int i = 0; i < f.Count; i += 3)
            {
                int a = f[i], b = f[i + 1], c = f[i + 2], ab = Mid(a, b), bc = Mid(b, c), ca = Mid(c, a);
                t.AddRange(new[] { a, ab, ca, b, bc, ab, c, ca, bc, ab, bc, ca });
            }
            // 감는 방향을 바깥쪽에 맞춘다
            for (int i = 0; i < t.Count; i += 3)
            {
                Vector3 a = v[t[i]], b = v[t[i + 1]], c = v[t[i + 2]];
                if (Vector3.Dot(Vector3.Cross(b - a, c - a), a + b + c) < 0) (t[i + 1], t[i + 2]) = (t[i + 2], t[i + 1]);
            }
            return (v, t);
        }

        // 정문 표시: 파란 기둥과 판
        static void Gate(GameObject root, Vector3 p)
        {
            var g = Child(root, "Gate");
            g.transform.position = p;
            Prim(g, PrimitiveType.Cylinder, "Pole", new Vector3(0, 2f, 0), Vector3.zero, new Vector3(0.18f, 2f, 0.18f), "Sign");
            Prim(g, PrimitiveType.Cube, "Board", new Vector3(0, 3.6f, 0), Vector3.zero, new Vector3(1.6f, 0.8f, 0.1f), "Sign");
        }

        // 정문 앞 '가상 세계' 표지(발표 사진이 실제 모습으로 오해되지 않게). 정문으로 들어오는 길(차도 먼저)에서 정문 10 m 바깥에
        // 길을 가로지르는 두 기둥 + 양면 판(정문 바로 옆 기와 건물과 겹치지 않게). 한글은 기본 글꼴에 없어
        // DataPrep/make_sign.py가 만든 그림(Data/virtual_sign.png)을 붙인다.
        static void VirtualSign(GameObject root, MapData data)
        {
            var start = new Vector3(data.start[0], 0, data.start[1]);
            var at = start; Vector3 dir = Vector3.forward; float w = 3f;
            foreach (var s in data.segs.OrderBy(x => x.road ? 0 : 1))
            {
                var pts = Pts(s.p);
                if (Vector3.Distance(pts[pts.Count - 1], start) < 0.5f) pts.Reverse();
                if (Vector3.Distance(pts[0], start) >= 0.5f) continue;
                float left = 10f; // 정문에서 길을 따라 10 m 바깥쪽
                for (int i = 0; i + 1 < pts.Count; i++)
                {
                    float d = Vector3.Distance(pts[i], pts[i + 1]);
                    at = Vector3.Lerp(pts[i], pts[i + 1], Mathf.Min(1, left / Mathf.Max(d, 1e-6f)));
                    dir = pts[i] - pts[i + 1]; // 정문 쪽(들어가는 방향)
                    if (left <= d) break;
                    left -= d;
                }
                w = s.w;
                break;
            }
            var g = Child(root, "VirtualSign");
            g.transform.SetPositionAndRotation(at + Vector3.up * groundFn(at.x, at.z), Quaternion.LookRotation(dir.normalized));
            float span = Mathf.Max(w + 1.2f, 6.4f), bw = span - 0.4f, bh = bw * 384f / 1024f, bottom = 2.6f;
            foreach (int k in new[] { -1, 1 })
            {
                var q = g.transform.TransformPoint(new Vector3(k * span / 2, 0, 0));
                float top = bottom + bh, gy = groundFn(q.x, q.z) - g.transform.position.y;
                Prim(g, PrimitiveType.Cylinder, $"Post_{(k < 0 ? "L" : "R")}", new Vector3(k * span / 2, (gy + top) / 2, 0), Vector3.zero,
                     new Vector3(0.2f, (top - gy) / 2, 0.2f), "Sign");
            }
            Prim(g, PrimitiveType.Cube, "Board", new Vector3(0, bottom + bh / 2, 0), Vector3.zero, new Vector3(bw + 0.2f, bh + 0.2f, 0.1f), "Sign");
            var mat = Mat("VirtualSign");
            mat.SetTexture("_BaseMap", AssetDatabase.LoadAssetAtPath<Texture2D>(Dir + "/Data/virtual_sign.png"));
            Prim(g, PrimitiveType.Quad, "Front", new Vector3(0, bottom + bh / 2, -0.06f), Vector3.zero, new Vector3(bw, bh, 1), "VirtualSign");
            Prim(g, PrimitiveType.Quad, "Back", new Vector3(0, bottom + bh / 2, 0.06f), new Vector3(0, 180, 0), new Vector3(bw, bh, 1), "VirtualSign");
        }

        static void SetupLook()
        {
            RenderSettings.fogStartDistance = 700f;
            RenderSettings.fogEndDistance = 3000f;
            var rp = AssetDatabase.LoadAssetAtPath<UniversalRenderPipelineAsset>("Assets/Settings/PC_RPAsset.asset");
            if (rp)
            {
                var so = new SerializedObject(rp);
                so.FindProperty("m_ShadowDistance").floatValue = 700f;
                so.ApplyModifiedProperties();
            }
            var sun = Object.FindObjectsByType<Light>(FindObjectsSortMode.None);
            foreach (var l in sun)
                if (l.type == LightType.Directional) l.transform.rotation = Quaternion.Euler(42, 35, 0);
        }

        // 보조 ------------------------------------------------------------------------
        static List<Vector3> Pts(float[] f)
        {
            var l = new List<Vector3>();
            for (int i = 0; i + 1 < f.Length; i += 2) l.Add(new Vector3(f[i], 0, f[i + 1]));
            return l;
        }

        static GameObject Place(GameObject parent, string name, Bld b)
        {
            var g = Child(parent, string.IsNullOrEmpty(b.name) ? name : $"{name}_{b.name}");
            var rot = Quaternion.Euler(0, -b.ang, 0);
            // 경사진 땅에서 뜨지 않게 바닥 네 모서리와 가운데 중 가장 낮은 땅 높이에 놓는다(높은 쪽은 땅에 조금 묻힘)
            float y = groundFn(b.cx, b.cz);
            foreach (var (sx, sz) in new[] { (-1, -1), (-1, 1), (1, -1), (1, 1) })
            {
                var q = new Vector3(b.cx, 0, b.cz) + rot * new Vector3(sx * b.w / 2, 0, sz * b.d / 2);
                y = Mathf.Min(y, groundFn(q.x, q.z));
            }
            g.transform.SetPositionAndRotation(new Vector3(b.cx, y, b.cz), rot);
            return g;
        }

        // 눈높이 시점: near에서 가장 가까운 보행로 꼭짓점에 서서 길 방향을 본다
        static void WalkView(GameObject root, Seg[] segs, Vector2 near)
        {
            Seg best = null;
            int bi = 0;
            float bd = float.MaxValue;
            foreach (var s in segs)
            {
                if (s.road) continue;
                for (int i = 0; i + 3 < s.p.Length; i += 2)
                {
                    float d = (new Vector2(s.p[i], s.p[i + 1]) - near).sqrMagnitude;
                    if (d < bd) { bd = d; best = s; bi = i; }
                }
            }
            if (best == null) return;
            var pts = Pts(best.p);
            int k = bi / 2, ahead = Mathf.Min(k + 3, pts.Count - 1);
            var eye = pts[k] + Vector3.up * 1.6f;
            View(root, $"ViewWalk_Seg{best.id}", eye, pts[ahead] + Vector3.up * 1.2f);
        }

        static GameObject View(GameObject parent, string name, Vector3 pos, Vector3 target)
        {
            var g = Child(parent, name);
            g.transform.position = pos + Vector3.up * groundFn(pos.x, pos.z);
            g.transform.LookAt(target + Vector3.up * groundFn(target.x, target.z));
            return g;
        }

        static float R(Random r, float a, float b) => a + (float)r.NextDouble() * (b - a);

        static GameObject Child(GameObject parent, string name)
        {
            var g = new GameObject(name);
            g.transform.SetParent(parent.transform, false);
            return g;
        }

        static GameObject Prim(GameObject parent, PrimitiveType type, string name, Vector3 pos, Vector3 rot, Vector3 scale, string mat)
        {
            var g = GameObject.CreatePrimitive(type);
            g.name = name;
            g.transform.SetParent(parent.transform, false);
            g.transform.localPosition = pos;
            g.transform.localEulerAngles = rot;
            g.transform.localScale = scale;
            g.GetComponent<MeshRenderer>().sharedMaterial = Mat(mat);
            return g;
        }

        static GameObject MeshObj(GameObject parent, string name, Mesh mesh, string mat) => MeshObj(parent, name, mesh, Mat(mat));

        static GameObject MeshObj(GameObject parent, string name, Mesh mesh, Material mat)
        {
            var g = Child(parent, name);
            g.AddComponent<MeshFilter>().sharedMesh = mesh;
            g.AddComponent<MeshRenderer>().sharedMaterial = mat;
            return g;
        }

        // 만든 메시는 모두 MinsokchonMeshes.asset 한 파일에 넣는다(장면 파일을 가볍게)
        static Mesh Store(Mesh m)
        {
            if (!storeMade) { AssetDatabase.CreateAsset(m, MeshPath); storeMade = true; }
            else AssetDatabase.AddObjectToAsset(m, MeshPath);
            return m;
        }

        class MB
        {
            public readonly List<Vector3> v = new List<Vector3>();
            readonly List<Vector2> uv = new List<Vector2>();
            readonly List<int> t = new List<int>();
            public int V(Vector3 p, Vector2 u) { v.Add(p); uv.Add(u); return v.Count - 1; }
            // 앞면 법선이 hint 쪽을 보도록 감는 방향을 고른다
            public void T(int a, int b, int c, Vector3 hint)
            {
                if (Vector3.Dot(Vector3.Cross(v[b] - v[a], v[c] - v[a]), hint) < 0) (b, c) = (c, b);
                t.Add(a); t.Add(b); t.Add(c);
            }
            public Mesh Build(string name)
            {
                var m = new Mesh { name = name, indexFormat = v.Count > 65000 ? IndexFormat.UInt32 : IndexFormat.UInt16 };
                m.SetVertices(v);
                m.SetUVs(0, uv);
                m.SetTriangles(t, 0);
                m.RecalculateNormals();
                m.RecalculateBounds();
                return Store(m);
            }
        }

        // 재질 ------------------------------------------------------------------------
        static Material RoofMat(float[] c)
        {
            // 항공사진 지붕 색을 0.06 단위로 묶어 재질 수를 줄인다
            var q = new Color(Mathf.Round(c[0] / 0.06f) * 0.06f, Mathf.Round(c[1] / 0.06f) * 0.06f, Mathf.Round(c[2] / 0.06f) * 0.06f);
            string name = $"Roof_{(int)(q.r * 100)}_{(int)(q.g * 100)}_{(int)(q.b * 100)}";
            var m = Mat(name, q * 1.15f, 0.15f);
            return m;
        }

        static Material Mat(string name)
        {
            if (name.StartsWith("Surf_")) return SurfMat(name);
            var (color, smooth, tex) = name switch
            {
                "Aerial" => (Color.white, 0f, null),
                "VirtualSign" => (Color.white, 0f, null),
                "Field" => (new Color(0.27f, 0.32f, 0.25f), 0f, null),
                "Road" => (new Color(0.36f, 0.36f, 0.37f), 0.1f, "Noise"),
                "Walk" => (new Color(0.70f, 0.67f, 0.61f), 0.05f, "Noise"),
                "Trail" => (new Color(0.62f, 0.56f, 0.45f), 0f, "Noise"),
                "StepStone" => (new Color(0.30f, 0.29f, 0.28f), 0.05f, null),
                "Basalt" => (new Color(0.36f, 0.34f, 0.32f), 0.05f, "Stones"),
                "Wood" => (new Color(0.42f, 0.30f, 0.20f), 0.1f, null),
                "Thatch" => (new Color(0.64f, 0.58f, 0.47f), 0f, "Thatch"),
                "Stone" => (new Color(0.62f, 0.60f, 0.56f), 0.05f, "Stones"),
                "Plaster" => (new Color(0.90f, 0.87f, 0.80f), 0.05f, null),
                "Giwa" => (new Color(0.30f, 0.32f, 0.34f), 0.15f, "Noise"),
                "Concrete" => (new Color(0.82f, 0.81f, 0.78f), 0.1f, null),
                "Leaf0" => (new Color(0.11f, 0.22f, 0.10f), 0.1f, null),
                "Leaf1" => (new Color(0.16f, 0.26f, 0.13f), 0.1f, null),
                "Leaf2" => (new Color(0.22f, 0.31f, 0.16f), 0.1f, null),
                "Bark" => (new Color(0.30f, 0.24f, 0.18f), 0.05f, null),
                "Sign" => (new Color(0.10f, 0.35f, 0.80f), 0.3f, null),
                "Glass" => (new Color(0.86f, 0.89f, 0.90f), 0.6f, null),
                "Grate" => (new Color(0.12f, 0.12f, 0.13f), 0.3f, null),
                "Barrier" => (new Color(0.95f, 0.45f, 0.10f), 0.2f, null),
                "Curb" => (new Color(0.85f, 0.75f, 0.20f), 0.1f, null),
                "Water" => (new Color(0.20f, 0.36f, 0.42f), 0.9f, null),
                _ => (Color.magenta, 0f, null),
            };
            var m = Mat(name, color, smooth);
            if (tex != null) m.SetTexture("_BaseMap", Tex(tex));
            return m;
        }

        // 노면 재질 13가지(측정 앱 MATERIALS)를 색으로 구분한다
        static Material SurfMat(string name)
        {
            var (color, tex) = name.Substring(5) switch
            {
                "asphalt" => (new Color(0.30f, 0.30f, 0.31f), "Noise"),
                "concrete" => (new Color(0.72f, 0.71f, 0.68f), "Noise"),
                "block" => (new Color(0.62f, 0.44f, 0.38f), "Stones"),
                "slab" => (new Color(0.78f, 0.74f, 0.66f), "Stones"),
                "stone" => (new Color(0.48f, 0.46f, 0.43f), "Stones"),
                "gravel" => (new Color(0.60f, 0.57f, 0.52f), "Noise"),
                "songi" => (new Color(0.52f, 0.24f, 0.17f), "Noise"),
                "soil" => (new Color(0.52f, 0.40f, 0.27f), "Noise"),
                "grass" => (new Color(0.30f, 0.46f, 0.22f), "Noise"),
                "deck" => (new Color(0.56f, 0.38f, 0.22f), null),
                "rubber" => (new Color(0.25f, 0.47f, 0.36f), null),
                "coir" => (new Color(0.62f, 0.50f, 0.31f), "Noise"),
                _ => (new Color(0.55f, 0.35f, 0.58f), null),
            };
            var m = Mat(name, color, 0.05f);
            if (tex != null) m.SetTexture("_BaseMap", Tex(tex));
            return m;
        }

        static Material Mat(string name, Color color, float smooth)
        {
            if (mats.TryGetValue(name, out var cached) && cached) return cached;
            if (!AssetDatabase.IsValidFolder(Dir + "/Materials")) AssetDatabase.CreateFolder(Dir, "Materials");
            var path = $"{Dir}/Materials/{name}.mat";
            var m = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (!m)
            {
                m = new Material(Shader.Find("Universal Render Pipeline/Lit"));
                AssetDatabase.CreateAsset(m, path);
            }
            m.SetColor("_BaseColor", color);
            m.SetFloat("_Smoothness", smooth);
            EditorUtility.SetDirty(m);
            return mats[name] = m;
        }

        // 무늬(흰색 바탕에 명암만, 색은 재질 색으로) -----------------------------------------------
        static Texture2D Tex(string kind)
        {
            var path = $"{Dir}/Materials/{kind}Tex.asset";
            var old = AssetDatabase.LoadAssetAtPath<Texture2D>(path);
            if (old) return old;
            const int S = 256;
            var tex = new Texture2D(S, S, TextureFormat.RGBA32, true) { wrapMode = TextureWrapMode.Repeat, anisoLevel = 4 };
            var px = new Color[S * S];
            var rnd = new Random(kind.GetHashCode());
            // 돌담·기단용 세포 무늬: 칸마다 무작위 점 하나, 가장 가까운 두 점 거리 차가 작으면 줄눈
            const int C = 6;
            var cells = new Vector2[C, C];
            for (int i = 0; i < C; i++) for (int j = 0; j < C; j++) cells[i, j] = new Vector2(i + R(rnd, 0.15f, 0.85f), j + R(rnd, 0.15f, 0.85f));
            var tone = new float[C, C];
            for (int i = 0; i < C; i++) for (int j = 0; j < C; j++) tone[i, j] = R(rnd, 0.75f, 1.1f);
            for (int y = 0; y < S; y++)
                for (int x = 0; x < S; x++)
                {
                    float u = (float)x / S, v = (float)y / S, val;
                    float n = Mathf.PerlinNoise(u * 24, v * 24) * 0.5f + Mathf.PerlinNoise(u * 64, v * 64) * 0.5f;
                    switch (kind)
                    {
                        case "Stones":
                        {
                            float gx = u * C, gy = v * C, d1 = 9, d2 = 9;
                            int bi = 0, bj = 0;
                            for (int di = -1; di <= 1; di++)
                                for (int dj = -1; dj <= 1; dj++)
                                {
                                    // 칸 번호는 감싸서(이음매 없는 무늬) 고르고, 위치는 감싸지 않은 칸 기준
                                    int ci = ((int)gx + di + C) % C, cj = ((int)gy + dj + C) % C;
                                    var pt = new Vector2(Mathf.Floor(gx) + di + (cells[ci, cj].x - ci), Mathf.Floor(gy) + dj + (cells[ci, cj].y - cj));
                                    float d = Vector2.Distance(new Vector2(gx, gy), pt);
                                    if (d < d1) { d2 = d1; d1 = d; bi = ci; bj = cj; } else if (d < d2) d2 = d;
                                }
                            val = d2 - d1 < 0.08f ? 0.45f : tone[bi, bj] * (0.85f + 0.3f * n);
                            break;
                        }
                        case "Thatch":
                        {
                            // 짚 결(가는 줄) + 0.5 m 간격 줄 격자(텍스처 한 장 = 2 m)
                            float streak = Mathf.PerlinNoise(u * 6, v * 90) * 0.35f + 0.8f;
                            float gu = Mathf.Abs((u * 4) % 1 - 0.5f), gv = Mathf.Abs((v * 4) % 1 - 0.5f);
                            bool rope = gu > 0.47f || gv > 0.47f;
                            val = rope ? 0.55f : streak * (0.9f + 0.2f * n);
                            break;
                        }
                        default:
                            val = 0.85f + 0.3f * n;
                            break;
                    }
                    px[y * S + x] = new Color(val, val, val, 1);
                }
            tex.SetPixels(px);
            tex.Apply(true);
            AssetDatabase.CreateAsset(tex, path);
            return tex;
        }
    }
}
