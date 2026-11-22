// 가상 세계 설계도(DataPrep/virtual_world.py가 만든 virtual_world.json)를 읽고 높이를 계산한다.
// 설계: Docs/2026-11-15-가상세계-설계.md. 가상 값이다(실제 민속촌 상태가 아님).
// s는 구간 첫 마디(a)에서 잰 m, 좌우(left/right)는 a→b 진행 방향 기준.
using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace Gildongmu.EditorTools
{
    public static class VirtualWorld
    {
        [Serializable] public class World { public int version, seed; public string pack, net, built; public Terr terrain; public VSeg[] segs; public VBld[] buildings_extra; public Wall[] walls; public Fence[] fences; public Water[] water; public Obs[] obstacles; public Fac[] facilities; }
        // 평면으로만 보이던 것(가상 세계 추가분): 빠진 건물, 돌담, 울타리, 연못
        [Serializable] public class VBld { public string kind, name, src; public int floors, front; public bool inSite; public float cx, cz, w, d, ang; public float[] roof, ring; public int[] tris; }
        [Serializable] public class Wall { public float[] p; public float h, t; public string src; }
        [Serializable] public class Fence { public string name, src; public float[] p; public float h; }
        [Serializable] public class Water { public float[] ring; public float level; public string src; }
        // 2·3차 항목(가상): 측정 앱의 장애물·시설 칸 중 3D에 쓰는 것만
        [Serializable] public class Obs { public string type, hazard, drop_side, guard, what, dir, src; public int seg; public float s, s_end, value, depth_m; }
        [Serializable] public class Fac { public string type, name, src, stall, place; public bool on_building; public int seg; public float s, x, z, s0, s1, w_cm, l_cm, sill_mm, slope; }
        [Serializable] public class Terr { public int n; public float cell, origin; public float[] h; }
        [Serializable] public class VSeg { public int id, a, b, width_cm; public float len, w; public float[] prof; public Cross[] cross; public Bump[] bumps; public Step[] steps; public Surf[] surf; }
        [Serializable] public class Cross { public float s0, s1, deg; public string low, src; }
        // unread · roadview: 제주대 거리뷰로 본 턱(2026-11-22, 측정 기록은 '못 잼'). 민속촌 자료에는 없어 기본값(false · null)
        [Serializable] public class Bump { public float s; public int mm, run_mm; public string dir, shape, src; public bool unread; public RoadviewNote roadview; }
        [Serializable] public class RoadviewNote { public int no; public string shape, lip, confidence; }
        [Serializable] public class Step { public float s0, s1, rise_m; public int count; public string src; }
        [Serializable] public class Surf { public float s0, s1; public string material, grade, src, reason; }

        public static string FilePath => Path.Combine(Application.dataPath, "Gildongmu/Minsokchon/Data/virtual_world.json");

        // 설계도가 없으면 null(지금처럼 평면 맵)
        public static World Load() => LoadFrom(FilePath);

        // 다른 대상지 설계도(같은 형식)를 경로로 읽는다. 없으면 null
        public static World LoadFrom(string path)
        {
            if (!File.Exists(path)) return null;
            return JsonUtility.FromJson<World>(File.ReadAllText(path));
        }

        public static float TerrainHeight(World w, float x, float z)
        {
            var t = w.terrain;
            float fx = Mathf.Clamp((x - t.origin) / t.cell, 0, t.n - 1.0001f);
            float fz = Mathf.Clamp((z - t.origin) / t.cell, 0, t.n - 1.0001f);
            int ix = (int)fx, iz = (int)fz;
            float tx = fx - ix, tz = fz - iz;
            float h00 = t.h[iz * t.n + ix], h01 = t.h[iz * t.n + ix + 1], h10 = t.h[(iz + 1) * t.n + ix], h11 = t.h[(iz + 1) * t.n + ix + 1];
            return Mathf.Lerp(Mathf.Lerp(h00, h01, tx), Mathf.Lerp(h10, h11, tx), tz);
        }

        // 같은 s가 두 번 있으면(턱·계단 단) 그 s에서는 뒤 높이
        public static float ProfileHeight(VSeg s, float x)
        {
            var p = s.prof;
            int n = p.Length / 2;
            if (x <= p[0]) return p[1];
            if (x >= p[(n - 1) * 2]) return p[(n - 1) * 2 + 1];
            int lo = 0, hi = n - 1; // p[lo*2] <= x < p[hi*2]
            while (hi - lo > 1)
            {
                int mid = (lo + hi) / 2;
                if (p[mid * 2] <= x) lo = mid; else hi = mid;
            }
            float s0 = p[lo * 2], s1 = p[hi * 2];
            return Mathf.Lerp(p[lo * 2 + 1], p[hi * 2 + 1], (x - s0) / Mathf.Max(s1 - s0, 1e-6f));
        }

        // 구간 선 위 s 자리(y = 0)와 그 선분의 방향. 선 길이를 구간 길이(len)에 맞춰 늘이거나 줄인다.
        public static (Vector3 pos, Vector3 dir) PointAt(float[] p, float len, float s)
        {
            int n = p.Length / 2;
            float total = 0;
            for (int i = 0; i + 1 < n; i++) total += Vector2.Distance(new Vector2(p[i * 2], p[i * 2 + 1]), new Vector2(p[i * 2 + 2], p[i * 2 + 3]));
            float t = Mathf.Clamp(s / len, 0, 1) * total, acc = 0;
            for (int i = 0; i + 1 < n; i++)
            {
                var a = new Vector3(p[i * 2], 0, p[i * 2 + 1]);
                var b = new Vector3(p[i * 2 + 2], 0, p[i * 2 + 3]);
                float d = Vector3.Distance(a, b);
                if (acc + d >= t || i + 2 == n)
                {
                    float u = d > 1e-6f ? Mathf.Clamp01((t - acc) / d) : 0;
                    return (Vector3.Lerp(a, b, u), d > 1e-6f ? (b - a) / d : Vector3.forward);
                }
                acc += d;
            }
            return (new Vector3(p[0], 0, p[1]), Vector3.forward);
        }

        // 꺾이는 곳에서 부드러운 진행 방향(앞뒤 0.5 m 점을 잇는 방향)
        public static Vector3 SmoothDir(float[] p, float len, float s)
        {
            var a = PointAt(p, len, Mathf.Max(0, s - 0.5f)).pos;
            var b = PointAt(p, len, Mathf.Min(len, s + 0.5f)).pos;
            var d = b - a;
            return d.sqrMagnitude > 1e-8f ? d.normalized : PointAt(p, len, s).dir;
        }

        // 선 꼭짓점의 s 값(띠가 꺾이는 곳을 따라가도록)
        public static float[] VertexS(float[] p, float len)
        {
            int n = p.Length / 2;
            var d = new float[n];
            for (int i = 1; i < n; i++) d[i] = d[i - 1] + Vector2.Distance(new Vector2(p[i * 2 - 2], p[i * 2 - 1]), new Vector2(p[i * 2], p[i * 2 + 1]));
            for (int i = 0; i < n; i++) d[i] = d[n - 1] > 0 ? d[i] / d[n - 1] * len : 0;
            return d;
        }

        // limit 넘게 꺾이는 꼭짓점의 s(Python sharp_corners와 같음)
        public static List<float> SharpCorners(float[] p, float len, float limitDeg = 30)
        {
            var vs = VertexS(p, len);
            var outS = new List<float>();
            for (int i = 1; i + 1 < p.Length / 2; i++)
            {
                var a = new Vector2(p[i * 2] - p[i * 2 - 2], p[i * 2 + 1] - p[i * 2 - 1]);
                var b = new Vector2(p[i * 2 + 2] - p[i * 2], p[i * 2 + 3] - p[i * 2 + 1]);
                if (a.sqrMagnitude < 1e-12f || b.sqrMagnitude < 1e-12f) continue;
                if (Vector2.Angle(a, b) > limitDeg) outS.Add(vs[i]);
            }
            return outS;
        }

        // 좌우 기울기(°)와 낮은 쪽이 왼쪽인지
        public static (float deg, bool lowLeft) CrossAt(VSeg s, float x)
        {
            if (s.cross != null)
                foreach (var c in s.cross)
                    if (c.s0 <= x && x <= c.s1) return (c.deg, c.low == "left");
            return (0, false);
        }

        public static bool InSteps(VSeg s, float x, float margin = 0)
        {
            if (s.steps != null)
                foreach (var st in s.steps)
                    if (st.s0 - margin <= x && x <= st.s1 + margin) return true;
            return false;
        }
    }
}
