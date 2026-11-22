// 제주대 아라캠퍼스 3D 맵(1:1,000 공개 지도 + 가상 값): DataPrep/jejunu/export_map.py가 만든 맵 자료(jejunu1000_map.json),
// build_world.py가 만든 설계도(virtual_world.json), 항공사진(aerial.jpg)으로 Jejunu1000 장면을 만든다.
// MinsokchonMaker.cs를 옮겨 적고 장소에 맞게 바꿨다(민속촌 파일은 고치지 않음). 설계: Docs/2026-11-15-제주대맵-설계.md 4장 바·6장 아.
// 좌표: 항공사진 가운데가 원점, x = 동쪽 m, z = 북쪽 m, y = 공개 지도 땅 높이(약 250~380 m).
// 길 구간 오브젝트 이름(Seg_<번호>)은 측정 앱 자료 파일의 구간 번호와 같다(공용 RouteView·VirtualCheck가 찾음).
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using Object = UnityEngine.Object;
using Random = System.Random;

namespace Gildongmu.EditorTools
{
    public static class JejunuMaker
    {
        const string RootName = "Jejunu1000";
        const string Dir = "Assets/Gildongmu/Jejunu1000";
        const string ScenePath = "Assets/Scenes/Jejunu1000.unity";
        const string MeshPath = Dir + "/Jejunu1000Meshes.asset";
        const string MapFile = "Gildongmu/Jejunu1000/Data/jejunu1000_map.json";
        const string WorldFile = "Gildongmu/Jejunu1000/Data/virtual_world.json";
        const float TreeTile = 80f;

        [Serializable] class MapData { public string site, name; public float mpp, sizeM; public int startNode; public float[] start; public float[] boundary; public Seg[] segs; public Line[] steps; public Bld[] buildings; public float[] trees; public WallLine[] walls; }
        [Serializable] class Seg { public int id, a, b; public bool road, drawn; public string kind; public float len, w; public float[] p; }
        [Serializable] class Line { public float[] p; }
        [Serializable] class WallLine { public float[] p; public float h, t; public string kind; }
        [Serializable] class Bld { public string kind, name; public int floors, front; public float cx, cz, w, d, ang; public float[] roof, ring; public int[] tris; }

        static readonly Dictionary<string, Material> mats = new Dictionary<string, Material>();
        static bool storeMade;

        [MenuItem("길동무/제주대 만들기")]
        public static string Make()
        {
            var clock = System.Diagnostics.Stopwatch.StartNew();
            var times = new List<string>();
            void Lap(string what) { times.Add($"{what} {clock.Elapsed.TotalSeconds:F0}s"); }

            string off = OpenScene();
            if (off.StartsWith("멈춤")) return off;
            var data = JsonUtility.FromJson<MapData>(File.ReadAllText(Path.Combine(Application.dataPath, MapFile)));
            var vw = VirtualWorld.LoadFrom(Path.Combine(Application.dataPath, WorldFile));
            if (vw == null) return "설계도 없음: " + WorldFile;
            mats.Clear();
            AssetDatabase.DeleteAsset(MeshPath);
            storeMade = false;
            var rnd = new Random(7);
            groundFn = (x, z) => VirtualWorld.TerrainHeight(vw, x, z);
            Lap("읽기");

            var root = new GameObject(RootName);
            VirtualGround(Child(root, "Ground"), data.sizeM, vw);
            Lap("땅");

            var paths = Child(root, "Paths");
            var vsegs = vw.segs.ToDictionary(v => v.id);
            var byNode = vw.segs.SelectMany(v => new[] { (n: v.a, v), (n: v.b, v) }).Distinct().ToLookup(x => x.n, x => x.v);
            int nPieces = 0, nSegs = 0, nNoPlan = 0;
            foreach (var s in data.segs)
            {
                if (!vsegs.TryGetValue(s.id, out var v)) { nNoPlan++; continue; }
                nPieces += VirtualPath(paths, s, v, byNode);
                nSegs++;
            }
            Physics.SyncTransforms();
            foreach (var s in data.segs)
                if (vsegs.TryGetValue(s.id, out var v)) Joints(paths.transform.Find($"Seg_{s.id}").gameObject, s, v, byNode, paths.transform);
            Lap("길");

            // 건물: 맵 자료는 모두 현대 건물(1:1,000 + 브이월드), 층수로 높이
            var houses = Child(root, "Buildings");
            int nModern = 0, nOtherKind = 0;
            for (int i = 0; i < data.buildings.Length; i++)
            {
                var b = data.buildings[i];
                if (b.kind != "modern") nOtherKind++;
                Modern(houses, b, i);
                nModern++;
            }
            // 설계도 더한 건물(지금 0동). 이름 규칙상 묶음은 늘 만든다(Floating이 찾음)
            var extraParent = Child(root, "BuildingsExtra");
            int nExtra = 0;
            for (int i = 0; i < (vw.buildings_extra?.Length ?? 0); i++)
            {
                var e = vw.buildings_extra[i];
                Modern(extraParent, new Bld { kind = e.kind, name = "", floors = e.floors, front = e.front, cx = e.cx, cz = e.cz, w = e.w, d = e.d, ang = e.ang, roof = e.roof, ring = e.ring, tris = e.tris }, 1000 + i);
                nExtra++;
            }
            Lap("건물");

            var (nWall, nRetain, nStone) = Walls(Child(root, "Walls"), vw.walls, data.walls);
            int nObs = Obstacles(Child(root, "Obstacles"), data.segs, vw);
            int nFac = Facilities(Child(root, "Facilities"), data.segs, vw);
            int nRv = RoadviewMarks(Child(root, "RoadviewMarks"), data.segs, vw);
            Lap("옹벽·장애물·시설");
            int nTrees = Trees(Child(root, "Trees"), data.trees, rnd);
            Lap("나무");
            Gate(root, new Vector3(data.start[0], groundFn(data.start[0], data.start[1]), data.start[1]));
            var (signAt, signDir, signSeg) = VirtualSign(root, data, vw);

            SetupLook();
            // 전체: 남쪽 높은 곳에서 캠퍼스 전체(한 변 약 1,340 m)를 내려다본다. 높이는 절대값(땅 약 250~380 m)
            var over = Child(root, "ViewOverview");
            over.transform.position = new Vector3(0, 1350, -950);
            over.transform.LookAt(new Vector3(0, 300, 40));
            // 정문 표지: 표지 앞쪽(Front가 보이는 쪽)에서 비스듬히
            var gate = Child(root, "ViewGate");
            var sideG = new Vector3(-signDir.z, 0, signDir.x);
            gate.transform.position = signAt - signDir * 13f + sideG * 4f + Vector3.up * 4f;
            gate.transform.LookAt(signAt + Vector3.up * 3.2f);
            string views = VirtualViews(root, data.segs, vw);
            Lap("표지·시점");

            var cam = Camera.main;
            if (cam)
            {
                cam.transform.SetPositionAndRotation(over.transform.position, over.transform.rotation);
                cam.farClipPlane = 6000;
            }

            EditorSceneManager.SaveScene(root.scene);
            AssetDatabase.SaveAssets();
            if (cam) SceneView.lastActiveSceneView?.AlignViewToObject(cam.transform);
            Lap("저장");
            int nSteps = vw.segs.Sum(v => v.steps.Length), nStepCount = vw.segs.Sum(v => v.steps.Sum(x => x.count));
            return $"제주대 만듦: 길 {nSegs}구간(설계도 없는 구간 {nNoPlan}), 노면·계단 토막 {nPieces}, 땅 {vw.terrain.n}x{vw.terrain.n}" +
                   $", 계단 {nSteps}곳({nStepCount}단), 턱 {vw.segs.Sum(v => v.bumps.Length)}" +
                   $", 건물 {nModern}동(modern 아닌 것 {nOtherKind}), 더한 건물 {nExtra}동, 옹벽·석축 {nWall}줄(옹벽 {nRetain}·석축 {nStone})" +
                   $", 3D 장애물 {nObs}개, 3D 시설 {nFac}개, 높이 모름 표시 {nRv}개, 나무 {nTrees}그루, 표지 구간 {signSeg}, 시점 {views}" +
                   $", 끈 루트 [{off}], 걸린 시간 {string.Join(", ", times)}";
        }

        // 제주대 장면이 열려 있으면 저장한다(사진·검사 뒤 저장 안 한 변경이 남지 않게). 다른 장면이면 아무것도 하지 않는다
        public static string Save()
        {
            var cur = EditorSceneManager.GetActiveScene();
            if (cur.path != ScenePath) return $"제주대 장면이 아님({cur.path}), 저장 안 함";
            bool dirty = cur.isDirty;
            if (dirty) EditorSceneManager.SaveScene(cur);
            AssetDatabase.SaveAssets();
            return $"{ScenePath}: 저장 전 변경 {(dirty ? "있었음 → 저장" : "없음")}, 지금 변경 {(EditorSceneManager.GetActiveScene().isDirty ? "있음" : "없음")}";
        }

        // 땅 높이(설계도 격자)
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

        // 2·3차 장애물(대부분 가상) 3D: 민속촌과 같다. 표에 3D 모양이 없는 종류(막다른 길, 진출입부 등)는 건너뛴다.
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

        // 3차 시설(대부분 가상) 3D: 민속촌과 같다
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

        // 거리뷰로 본 턱(높이 모름, 2026-11-22): 길을 가로지르는 주황 띠(경로 그림 '확인 필요'와 같은 주황) + 길 가장자리 짧은 기둥.
        // 턱 높이는 가상 값 그대로이고, 측정 기록에서는 '못 잼'이다. 충돌체는 없앤다(길 검사·시뮬레이션에 걸리지 않게)
        static int RoadviewMarks(GameObject parent, Seg[] segs, VirtualWorld.World w)
        {
            var map = segs.ToDictionary(x => x.id);
            int n = 0;
            foreach (var v in w.segs)
            {
                if (v.bumps == null || !map.TryGetValue(v.id, out var s)) continue;
                foreach (var b in v.bumps)
                {
                    if (!b.unread) continue;
                    var g = Child(parent, $"Unknown_{v.id}_{b.s:F1}_no{(b.roadview != null ? b.roadview.no : 0)}");
                    var (p, dir, _) = OnPath(s, v, b.s);
                    // 길 표면은 높이 단면 + 0.05 m(OnPath와 같음). 턱 앞뒤 중 높은 쪽 표면 위 3 cm에 띠
                    p.y = Mathf.Max(VirtualWorld.ProfileHeight(v, Mathf.Max(0, b.s - 0.2f)), VirtualWorld.ProfileHeight(v, Mathf.Min(v.len, b.s + 0.2f))) + 0.08f;
                    var band = Prim(g, PrimitiveType.Cube, "Band", p, Vector3.zero, new Vector3(v.w + 0.1f, 0.02f, 0.3f), "Unknown");
                    band.transform.rotation = Quaternion.LookRotation(dir);
                    var (q, _, _) = OnPath(s, v, b.s, v.w / 2 + 0.15f);
                    q.y = p.y;
                    var post = Prim(g, PrimitiveType.Cylinder, "Post", q + Vector3.up * 1.0f, Vector3.zero, new Vector3(0.12f, 1.0f, 0.12f), "Unknown");
                    var head = Prim(g, PrimitiveType.Cube, "Head", q + Vector3.up * 2.15f, Vector3.zero, new Vector3(0.4f, 0.3f, 0.4f), "Unknown");
                    foreach (var c in new[] { band, post, head }) Object.DestroyImmediate(c.GetComponent<Collider>());
                    n++;
                }
            }
            return n;
        }

        // 옹벽·석축(1:1,000, 높이 h, 두께 t). 땅은 벽 선에서 끊겨 있으므로(오르막 쪽 +h/2, 내리막 쪽 -h/2)
        // 꼭짓점마다 선과 양옆 1.5 m의 땅 높이를 보고, 밑은 가장 낮은 땅 - 0.1 m, 위는 max(밑 + h, 가장 높은 땅) + 0.1 m.
        // 재질은 맵 자료 kind(옹벽 → 콘크리트, 석축 → 현무암). 반환: (줄 수, 옹벽, 석축)
        static (int all, int retain, int stone) Walls(GameObject parent, VirtualWorld.Wall[] walls, WallLine[] kinds)
        {
            if (walls == null) return (0, 0, 0);
            var mbs = new Dictionary<string, MB>();
            int count = 0, nR = 0, nS = 0, part = 0;
            for (int wi = 0; wi < walls.Length; wi++)
            {
                var w = walls[wi];
                var pts = Pts(w.p);
                if (pts.Count < 2) continue;
                bool stone = kinds != null && kinds.Length == walls.Length && kinds[wi].kind == "석축";
                string mat = stone ? "Basalt" : "Retaining";
                if (stone) nS++; else nR++;
                if (!mbs.TryGetValue(mat, out var mb)) mbs[mat] = mb = new MB();
                var lo = new float[pts.Count];
                var hi = new float[pts.Count];
                for (int k = 0; k < pts.Count; k++)
                {
                    var din = k > 0 ? (pts[k] - pts[k - 1]).normalized : Vector3.zero;
                    var dout = k + 1 < pts.Count ? (pts[k + 1] - pts[k]).normalized : Vector3.zero;
                    var t = din + dout; if (t.sqrMagnitude < 1e-6f) t = dout != Vector3.zero ? dout : din;
                    var nrm = new Vector3(-t.z, 0, t.x).normalized;
                    float g0 = groundFn(pts[k].x, pts[k].z);
                    var a = pts[k] + nrm * 1.5f; var b = pts[k] - nrm * 1.5f;
                    float ga = groundFn(a.x, a.z), gb = groundFn(b.x, b.z);
                    float low = Mathf.Min(g0, Mathf.Min(ga, gb)), high = Mathf.Max(g0, Mathf.Max(ga, gb));
                    lo[k] = low - 0.1f;
                    hi[k] = Mathf.Max(low + w.h, high) + 0.1f;
                }
                for (int k = 0; k + 1 < pts.Count; k++)
                {
                    var a = pts[k]; var b = pts[k + 1];
                    var d = b - a; if (d.sqrMagnitude < 1e-6f) continue;
                    var side = new Vector3(-d.z, 0, d.x).normalized * (Mathf.Max(w.t, 0.2f) / 2);
                    var q = new[] { a + side, b + side, b - side, a - side };
                    var yl = new[] { lo[k], lo[k + 1], lo[k + 1], lo[k] };
                    var yh = new[] { hi[k], hi[k + 1], hi[k + 1], hi[k] };
                    var v = new int[8];
                    for (int c = 0; c < 4; c++) { v[c] = mb.V(new Vector3(q[c].x, yl[c], q[c].z), new Vector2(q[c].x / 2f, yl[c] / 2f)); v[c + 4] = mb.V(new Vector3(q[c].x, yh[c], q[c].z), new Vector2(q[c].x / 2f, yh[c] / 2f)); }
                    // 옆 두 면, 끝 두 면, 윗면
                    mb.T(v[0], v[1], v[5], side); mb.T(v[0], v[5], v[4], side);
                    mb.T(v[2], v[3], v[7], -side); mb.T(v[2], v[7], v[6], -side);
                    mb.T(v[3], v[0], v[4], -d); mb.T(v[3], v[4], v[7], -d);
                    mb.T(v[1], v[2], v[6], d); mb.T(v[1], v[6], v[5], d);
                    mb.T(v[4], v[5], v[6], Vector3.up); mb.T(v[4], v[6], v[7], Vector3.up);
                }
                count++;
                if (mb.v.Count > 60000) { part++; MeshObj(parent, $"Walls_{mat}_{part}", mb.Build($"Walls_{mat}_{part}"), mat); mbs[mat] = new MB(); }
            }
            foreach (var kv in mbs)
                if (kv.Value.v.Count > 0) MeshObj(parent, $"Walls_{kv.Key}_last", kv.Value.Build($"Walls_{kv.Key}_last"), kv.Key);
            return (count, nR, nS);
        }

        // 땅: 설계도 높이 격자 그대로(671x671, 메시 인덱스 32비트) + 항공사진(가운데가 원점, 한 변 sizeM) ----------
        static void VirtualGround(GameObject parent, float size, VirtualWorld.World w)
        {
            var texPath = Dir + "/Data/aerial.jpg";
            var imp = (TextureImporter)AssetImporter.GetAtPath(texPath);
            // 5376 화소를 그대로 쓴다(기본값이면 2048로 줄어 흐려짐)
            if (imp && (imp.maxTextureSize != 8192 || imp.npotScale != TextureImporterNPOTScale.None || imp.anisoLevel != 9 || imp.textureCompression != TextureImporterCompression.CompressedHQ || imp.wrapMode != TextureWrapMode.Clamp))
            {
                imp.maxTextureSize = 8192;
                imp.npotScale = TextureImporterNPOTScale.None;
                imp.anisoLevel = 9;
                imp.textureCompression = TextureImporterCompression.CompressedHQ;
                imp.wrapMode = TextureWrapMode.Clamp;
                imp.SaveAndReimport();
            }
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
            MeshObj(parent, "Terrain", mb.Build("Terrain", true), "Aerial");

            var outer = new MB();
            float o = 5000f, y = minH - 0.1f;
            int oa = outer.V(new Vector3(-o, y, -o), Vector2.zero), ob = outer.V(new Vector3(o, y, -o), Vector2.zero);
            int oc = outer.V(new Vector3(o, y, o), Vector2.zero), od = outer.V(new Vector3(-o, y, o), Vector2.zero);
            outer.T(oa, ob, oc, Vector3.up); outer.T(oa, oc, od, Vector3.up);
            MeshObj(parent, "Outer", outer.Build("Outer"), "Field");
        }

        // 가상 길(민속촌과 같음): 높이 단면을 따라 오르내리고, 좌우 기울기 토막에서 옆으로 기운 띠.
        // 노면 토막·계단마다 따로 그물(재질 Surf_<재질>, 계단은 StepStone)과 MeshCollider. 반환: 토막 수
        static int VirtualPath(GameObject paths, Seg s, VirtualWorld.VSeg v, ILookup<int, VirtualWorld.VSeg> byNode)
        {
            var seg = Child(paths, $"Seg_{s.id}");
            // 계단 끝을 먼저 넣고, 노면 토막 끝이 그와 5 mm 안이면 넣지 않는다(설계도 반올림으로 1 mm 토막이 생겨
            // 꼭짓점이 셋 미만인 충돌 메시가 되던 것: Seg 30·238·610·1121)
            var cuts = new List<float> { 0, v.len };
            foreach (var x in v.steps.Select(st => new[] { st.s0, st.s1 }).Concat(v.surf.Select(sf => new[] { sf.s0, sf.s1 })))
                foreach (float c in x)
                    if (!cuts.Any(o => Mathf.Abs(o - c) < 0.005f)) cuts.Add(c);
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
            return pieces;
        }

        // 양 끝 둥근 판(이웃 구간과 만나는 곳의 빈틈 메우기, 충돌체 없음). 계단 끝에는 두지 않는다.
        // 민속촌과 달리 모든 길 조각(충돌체)을 지은 뒤에 만들고, 판의 점 아래에 길 면이 있으면 그 면 + 3 cm보다 높지 않게 낮춘다.
        // 제주대는 넓은 차도(폭 7~12 m) 끝 판이 이어지지 않은 낮은 보도·계단 위로 나가 0.3~0.9 m 떠 보였다(Floating 82개).
        static void Joints(GameObject seg, Seg s, VirtualWorld.VSeg v, ILookup<int, VirtualWorld.VSeg> byNode, Transform pathsT)
        {
            float PathTop(Vector3 p)
            {
                float best = float.NaN;
                foreach (var hit in Physics.RaycastAll(new Vector3(p.x, 1000, p.z), Vector3.down, 2000))
                    if (hit.collider.transform.IsChildOf(pathsT) && (float.IsNaN(best) || hit.point.y > best)) best = hit.point.y;
                return best;
            }
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
                        float top = PathTop(q);
                        if (!float.IsNaN(top) && q.y > top + 0.03f) q.y = top + 0.03f;
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

        // [a, b] 토막의 띠(민속촌과 같음). 줄(가로 단면)은 높이 단면의 점(같은 s 두 번 = 턱·계단 단), 선 꼭짓점, 좌우 토막 끝에 둔다.
        static Mesh VirtualRibbon(Seg s, VirtualWorld.VSeg v, float a, float b, float[] vertexS, string name)
        {
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
            int pl = -1, pr = -1, pside = 0;
            float ps = 0, ph = 0;
            Vector3 pdir = Vector3.forward;
            foreach (var (sx, h, sideRow) in rows)
            {
                // 꺾인 꼭짓점(들어오는 줄 -1 → 나가는 줄 +1)은 민속촌처럼 사각형 둘로 메우지 않고 가운데 점에서 부채꼴 두 개로 메운다.
                // 사각형으로 메우면 대각선 때문에 꼭짓점 높이 면이 가운데선을 따라 앞으로 (폭/2)·tan(꺾인 각) 만큼 나와,
                // 꼭짓점 바로 뒤 턱이 덮였다(구간 91: 10° 꺾임, 폭 9.5 m, 턱이 꼭짓점 1 cm 뒤)
                if (sideRow > 0 && pside < 0 && pl >= 0 && Mathf.Abs(sx - ps) < 1e-6f)
                {
                    var pos0 = VirtualWorld.PointAt(s.p, v.len, sx).pos;
                    var dirOut = VirtualWorld.PointAt(s.p, v.len, Mathf.Min(v.len, sx + 1e-3f)).dir;
                    var leftOut = new Vector3(-dirOut.z, 0, dirOut.x);
                    var (deg0, lowLeft0) = VirtualWorld.CrossAt(v, sx);
                    float tilt0 = v.w / 2 * Mathf.Tan(deg0 * Mathf.Deg2Rad), y0 = h + 0.05f;
                    var L0 = pos0 + leftOut * (v.w / 2); L0.y = y0 + (lowLeft0 ? -tilt0 : tilt0);
                    var R0 = pos0 - leftOut * (v.w / 2); R0.y = y0 + (lowLeft0 ? tilt0 : -tilt0);
                    int c0 = mb.V(new Vector3(pos0.x, y0, pos0.z), new Vector2(pos0.x / 3f, pos0.z / 3f));
                    int l0 = mb.V(L0, new Vector2(L0.x / 3f, L0.z / 3f)), r0 = mb.V(R0, new Vector2(R0.x / 3f, R0.z / 3f));
                    mb.T(c0, pl, l0, Vector3.up); mb.T(c0, pr, r0, Vector3.up);
                    pl = l0; pr = r0; ps = sx; ph = h; pdir = dirOut; pside = sideRow;
                    continue;
                }
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
                    var hint = Vector3.up * (sx - ps) - pdir * (h - ph);
                    if (hint.sqrMagnitude < 1e-10f) hint = Vector3.up;
                    mb.T(pl, li, ri, hint); mb.T(pl, ri, pr, hint);
                }
                pl = li; pr = ri; ps = sx; ph = h; pdir = dir; pside = sideRow;
            }
            return mb.Build(name);
        }

        // 확인용 시점(설계도에서 고름): 가장 가파른 길, 가장 긴 계단, 높은 턱(보도·건너는 곳), 재질이 바뀌는 곳. 반환: 고른 구간
        static string VirtualViews(GameObject root, Seg[] segs, VirtualWorld.World w)
        {
            var map = segs.ToDictionary(x => x.id);
            var picked = new List<string>();
            // back > 0이면 진행 방향 뒤(s 작은 쪽), < 0이면 앞에서 본다. side는 왼쪽 m
            void Look(string name, Seg s, VirtualWorld.VSeg v, float at, float back, float side, float up)
            {
                var (pos, _) = VirtualWorld.PointAt(s.p, v.len, at);
                var dir = VirtualWorld.SmoothDir(s.p, v.len, at);
                var left = new Vector3(-dir.z, 0, dir.x);
                float h = VirtualWorld.ProfileHeight(v, at);
                // 길 높이 기준으로 직접 놓는다
                var g = Child(root, name).transform;
                g.position = pos - dir * back + left * side + Vector3.up * (h + up);
                g.LookAt(pos + Vector3.up * (h + 0.2f));
                picked.Add($"{name}=Seg_{s.id}@{at:F1}");
            }
            // 오르막·계단은 낮은 쪽에서 올려다본다(높은 쪽에서 보면 나무·둔덕에 가렸다)
            float LowSide(VirtualWorld.VSeg v) => VirtualWorld.ProfileHeight(v, v.len) < VirtualWorld.ProfileHeight(v, 0) ? -1f : 1f;
            var cand = w.segs.Where(v => map.ContainsKey(v.id)).ToList();

            var steep = cand.Where(v => v.steps.Length == 0 && v.len > 8)
                .OrderByDescending(v => Mathf.Abs(VirtualWorld.ProfileHeight(v, v.len) - VirtualWorld.ProfileHeight(v, 0)) / v.len).FirstOrDefault();
            if (steep != null) Look("ViewSlope", map[steep.id], steep, steep.len / 2, LowSide(steep) * 14, 3, 3);
            var st = cand.Where(v => v.steps.Length > 0).OrderByDescending(v => v.steps.Sum(x => x.count)).FirstOrDefault();
            if (st != null)
            {
                float mid = (st.steps[0].s0 + st.steps[0].s1) / 2, half = (st.steps[0].s1 - st.steps[0].s0) / 2;
                Look("ViewSteps", map[st.id], st, mid, LowSide(st) * (half + 9), 4, 4);
            }
            // 턱: 보도·건너는 곳의 높은 턱(100 mm 넘는 일반 연석). 넓은 보도에서 잘 보인다. 없으면 아무 턱
            var bump = cand.Where(v => !map[v.id].road && v.bumps.Any(b => b.mm >= 100)).OrderByDescending(v => v.w).ThenBy(v => v.id).FirstOrDefault()
                       ?? cand.FirstOrDefault(v => v.bumps.Length > 0);
            if (bump != null) Look("ViewBump", map[bump.id], bump, bump.bumps.OrderByDescending(b => b.mm).First().s, 4f, 2f, 1.5f);
            var sf = cand.FirstOrDefault(v => v.surf.Length >= 2 && v.surf[0].material != v.surf[1].material && v.steps.Length == 0 && v.len > 10);
            if (sf != null) Look("ViewSurface", map[sf.id], sf, sf.surf[0].s1, 8, 3, 3f);
            return string.Join(" ", picked);
        }

        // 샘플 장면을 복사해 카메라·해·후처리를 그대로 쓰고, 복사본 안의 다른 루트(Village 등)는 끈다.
        // 민속촌 장면은 열지 않는다. 지금 장면에 저장 안 한 변경이 있으면(다른 장면) 멈춘다. 반환: 끈 루트 이름(멈추면 "멈춤…")
        static string OpenScene()
        {
            var cur = EditorSceneManager.GetActiveScene();
            if (cur.path != ScenePath && cur.isDirty) return $"멈춤: 지금 장면({cur.path})에 저장 안 한 변경이 있음";
            if (!File.Exists(ScenePath)) AssetDatabase.CopyAsset("Assets/Scenes/SampleScene.unity", ScenePath);
            if (cur.path != ScenePath) EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
            var off = new List<string>();
            foreach (var g in EditorSceneManager.GetActiveScene().GetRootGameObjects())
            {
                if (g.name == RootName) { Object.DestroyImmediate(g); continue; }
                if (g.GetComponent<Camera>() || g.GetComponent<Light>() || g.GetComponent<Volume>()) continue;
                if (g.activeSelf) g.SetActive(false);
                off.Add(g.name);
            }
            return string.Join(" ", off);
        }

        // 현대 건물: 윤곽을 층수 x 3.4 m로 올리고, 지붕은 항공사진 색.
        // 비탈(제주대는 높이 차가 큼)에서 뜨지 않게 윤곽 선(1 m 간격)과 가운데 중 가장 낮은 땅 높이에 놓고,
        // 높은 쪽이 묻히지 않게 벽 높이에 윤곽 안 땅 높이 차를 더한다(낮은 쪽은 기초가 드러난 모양).
        static void Modern(GameObject parent, Bld b, int i)
        {
            var ring = Pts(b.ring);
            var cen = Vector3.zero;
            foreach (var q in ring) cen += q;
            cen /= ring.Count;
            float gLo = groundFn(cen.x, cen.z), gHi = gLo;
            for (int k = 0; k < ring.Count; k++)
            {
                var p0 = ring[k]; var p1 = ring[(k + 1) % ring.Count];
                int steps = Mathf.Max(1, Mathf.CeilToInt(Vector3.Distance(p0, p1)));
                for (int j = 0; j < steps; j++)
                {
                    var q = Vector3.Lerp(p0, p1, j / (float)steps);
                    float gy = groundFn(q.x, q.z);
                    gLo = Mathf.Min(gLo, gy); gHi = Mathf.Max(gHi, gy);
                }
            }
            float h = Mathf.Max(b.floors, 1) * 3.4f + (gHi - gLo);
            var mb = new MB();
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
            g.transform.position = new Vector3(0, gLo, 0);
            MeshObj(g, "Walls", walls, "Concrete");
            MeshObj(g, "Top", top.Build($"ModernTop_{i}"), RoofMat(b.roof));
        }

        // 나무: 80 m 칸마다 재질별로 한 메시에 모은다(약 2만 그루라 오브젝트를 줄임). 민속촌과 같다 ---------------------
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
                int shade = Mathf.Clamp((int)t[i + 3], 0, 2);
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
                // 비탈에서 줄기 밑이 뜨지 않게 0.3 m 묻는다
                for (int k = 0; k < 6; k++)
                {
                    float a = k * Mathf.PI / 3;
                    var dir = new Vector3(Mathf.Cos(a), 0, Mathf.Sin(a));
                    trunk.v.Add(new Vector3(x, gy - 0.3f, z) + dir * tr); trunk.n.Add(dir);
                    trunk.v.Add(new Vector3(x, gy + top, z) + dir * tr * 0.7f); trunk.n.Add(dir);
                }
                for (int k = 0; k < 6; k++)
                {
                    int a0 = baseIdx + k * 2, a1 = baseIdx + ((k + 1) % 6) * 2;
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
            for (int i = 0; i < t.Count; i += 3)
            {
                Vector3 a = v[t[i]], b = v[t[i + 1]], c = v[t[i + 2]];
                if (Vector3.Dot(Vector3.Cross(b - a, c - a), a + b + c) < 0) (t[i + 1], t[i + 2]) = (t[i + 2], t[i + 1]);
            }
            return (v, t);
        }

        // 정문 출발점 표시: 파란 기둥과 판
        static void Gate(GameObject root, Vector3 p)
        {
            var g = Child(root, "Gate");
            g.transform.position = p;
            Prim(g, PrimitiveType.Cylinder, "Pole", new Vector3(0, 2f, 0), Vector3.zero, new Vector3(0.18f, 2f, 0.18f), "Sign");
            Prim(g, PrimitiveType.Cube, "Board", new Vector3(0, 3.6f, 0), Vector3.zero, new Vector3(1.6f, 0.8f, 0.1f), "Sign");
        }

        // '공개 지도 + 가상 값' 표지(발표 사진이 실측 모습으로 오해되지 않게). 정문 출발 마디(startNode)와 그 이웃 마디에 닿는
        // 보행 구간(차도·건너는 곳·출입·계단 빼고, 6 m 이상) 가운데 가장 넓은 것 위, 이웃 마디에서 10 m(짧으면 가운데)에
        // 길을 가로지르는 두 기둥 + 양면 판. Front는 정문 쪽으로 걸어오는 사람에게 보인다.
        // 한글은 기본 글꼴에 없어 DataPrep/jejunu/make_sign.py가 만든 그림(Data/virtual_sign.png)을 붙인다.
        static (Vector3 at, Vector3 dir, int seg) VirtualSign(GameObject root, MapData data, VirtualWorld.World w)
        {
            var vs = w.segs.ToDictionary(v => v.id);
            int start = data.startNode;
            var near = new HashSet<int> { start };
            foreach (var s in data.segs.Where(s => s.a == start || s.b == start)) { near.Add(s.a); near.Add(s.b); }
            var skip = new HashSet<string> { "entrance", "crossing", "steps", "road_campus", "road_public", "driveway" };
            var pick = data.segs.Where(s => !s.road && !skip.Contains(s.kind ?? "") && s.len >= 6 && vs.ContainsKey(s.id) && vs[s.id].steps.Length == 0
                                            && (near.Contains(s.a) || near.Contains(s.b)))
                                .OrderBy(s => s.a == start || s.b == start ? 0 : 1).ThenByDescending(s => s.w).ThenBy(s => s.id).FirstOrDefault();
            Vector3 at, dir; float wid = 3f; int segId = -1;
            if (pick != null)
            {
                var v = vs[pick.id];
                bool fromA = near.Contains(pick.a);
                float d = Mathf.Min(10f, v.len / 2), sAt = fromA ? d : v.len - d;
                var (p, _) = VirtualWorld.PointAt(pick.p, v.len, sAt);
                var sd = VirtualWorld.SmoothDir(pick.p, v.len, sAt);
                at = p; dir = fromA ? -sd : sd; // 이웃(정문) 마디 쪽
                wid = pick.w; segId = pick.id;
            }
            else
            {
                at = new Vector3(data.start[0], 0, data.start[1]) + Vector3.forward * 5f; dir = Vector3.back;
            }
            var g = Child(root, "VirtualSign");
            g.transform.SetPositionAndRotation(at + Vector3.up * groundFn(at.x, at.z), Quaternion.LookRotation(dir.normalized));
            // 폭은 길 + 1.2 m(최소 4.5 m). 민속촌의 최소 6.4 m면 정문 옆 버스 정류장 건물과 기둥이 겹쳤다
            float span = Mathf.Max(wid + 1.2f, 4.5f), bw = span - 0.4f, bh = bw * 384f / 1024f, bottom = 2.6f;
            foreach (int k in new[] { -1, 1 })
            {
                var q = g.transform.TransformPoint(new Vector3(k * span / 2, 0, 0));
                float top = bottom + bh, gy = groundFn(q.x, q.z) - g.transform.position.y - 0.3f;
                Prim(g, PrimitiveType.Cylinder, $"Post_{(k < 0 ? "L" : "R")}", new Vector3(k * span / 2, (gy + top) / 2, 0), Vector3.zero,
                     new Vector3(0.2f, (top - gy) / 2, 0.2f), "Sign");
            }
            Prim(g, PrimitiveType.Cube, "Board", new Vector3(0, bottom + bh / 2, 0), Vector3.zero, new Vector3(bw + 0.2f, bh + 0.2f, 0.1f), "Sign");
            var mat = Mat("VirtualSign");
            mat.SetTexture("_BaseMap", AssetDatabase.LoadAssetAtPath<Texture2D>(Dir + "/Data/virtual_sign.png"));
            Prim(g, PrimitiveType.Quad, "Front", new Vector3(0, bottom + bh / 2, -0.06f), Vector3.zero, new Vector3(bw, bh, 1), "VirtualSign");
            Prim(g, PrimitiveType.Quad, "Back", new Vector3(0, bottom + bh / 2, 0.06f), new Vector3(0, 180, 0), new Vector3(bw, bh, 1), "VirtualSign");
            return (g.transform.position, dir.normalized, segId);
        }

        // 장면 안개·해(장면 설정만. 공용 렌더 파이프라인 자산 PC_RPAsset은 건드리지 않는다)
        static void SetupLook()
        {
            RenderSettings.fogStartDistance = 1500f;
            RenderSettings.fogEndDistance = 6000f;
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

        // pos·target은 땅 위 높이(땅 높이를 더함)
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

        // 만든 메시는 모두 Jejunu1000Meshes.asset 한 파일에 넣는다(장면 파일을 가볍게)
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
            // big = true면 꼭짓점 수와 상관없이 32비트 인덱스(땅 671x671 = 45만 꼭짓점)
            public Mesh Build(string name, bool big = false)
            {
                var m = new Mesh { name = name, indexFormat = big || v.Count > 65000 ? IndexFormat.UInt32 : IndexFormat.UInt16 };
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
            if (c == null || c.Length < 3) return Mat("Concrete");
            var q = new Color(Mathf.Round(c[0] / 0.06f) * 0.06f, Mathf.Round(c[1] / 0.06f) * 0.06f, Mathf.Round(c[2] / 0.06f) * 0.06f);
            string name = $"Roof_{(int)(q.r * 100)}_{(int)(q.g * 100)}_{(int)(q.b * 100)}";
            return Mat(name, q * 1.15f, 0.15f);
        }

        static Material Mat(string name)
        {
            if (name.StartsWith("Surf_")) return SurfMat(name);
            var (color, smooth, tex) = name switch
            {
                "Aerial" => (Color.white, 0f, null),
                "VirtualSign" => (Color.white, 0f, null),
                "Field" => (new Color(0.27f, 0.32f, 0.25f), 0f, null),
                "StepStone" => (new Color(0.30f, 0.29f, 0.28f), 0.05f, null),
                "Basalt" => (new Color(0.36f, 0.34f, 0.32f), 0.05f, "Stones"),
                "Retaining" => (new Color(0.66f, 0.65f, 0.62f), 0.05f, "Noise"),
                "Wood" => (new Color(0.42f, 0.30f, 0.20f), 0.1f, null),
                "Stone" => (new Color(0.62f, 0.60f, 0.56f), 0.05f, "Stones"),
                "Concrete" => (new Color(0.82f, 0.81f, 0.78f), 0.1f, null),
                "Leaf0" => (new Color(0.11f, 0.22f, 0.10f), 0.1f, null),
                "Leaf1" => (new Color(0.16f, 0.26f, 0.13f), 0.1f, null),
                "Leaf2" => (new Color(0.22f, 0.31f, 0.16f), 0.1f, null),
                "Bark" => (new Color(0.30f, 0.24f, 0.18f), 0.05f, null),
                "Sign" => (new Color(0.10f, 0.35f, 0.80f), 0.3f, null),
                "Grate" => (new Color(0.12f, 0.12f, 0.13f), 0.3f, null),
                "Barrier" => (new Color(0.95f, 0.45f, 0.10f), 0.2f, null),
                "Curb" => (new Color(0.85f, 0.75f, 0.20f), 0.1f, null),
                "Unknown" => (new Color(0.91f, 0.46f, 0.17f), 0.2f, null),  // RouteView 'uncertain'(#E8762B)과 같은 주황
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
                    if (kind == "Stones")
                    {
                        float gx = u * C, gy = v * C, d1 = 9, d2 = 9;
                        int bi = 0, bj = 0;
                        for (int di = -1; di <= 1; di++)
                            for (int dj = -1; dj <= 1; dj++)
                            {
                                int ci = ((int)gx + di + C) % C, cj = ((int)gy + dj + C) % C;
                                var pt = new Vector2(Mathf.Floor(gx) + di + (cells[ci, cj].x - ci), Mathf.Floor(gy) + dj + (cells[ci, cj].y - cj));
                                float d = Vector2.Distance(new Vector2(gx, gy), pt);
                                if (d < d1) { d2 = d1; d1 = d; bi = ci; bj = cj; } else if (d < d2) d2 = d;
                            }
                        val = d2 - d1 < 0.08f ? 0.45f : tone[bi, bj] * (0.85f + 0.3f * n);
                    }
                    else val = 0.85f + 0.3f * n;
                    px[y * S + x] = new Color(val, val, val, 1);
                }
            tex.SetPixels(px);
            tex.Apply(true);
            AssetDatabase.CreateAsset(tex, path);
            return tex;
        }
    }
}
