/* 길동무 앱 안 길찾기(B단계 사람마다 조절, 2026-11-22). 계획: Unity Docs/2026-11-22-B단계-작업계획.md
   DataPrep/route_engine.py의 _edges · _dijkstra_w · _find_route_w · three_routes와 route_export.cost_from을 그대로 옮겼다.
   자료는 route_export.export_graph(bf-route-graph-1). DOM을 쓰지 않아 브라우저와 Node(시험) 둘 다에서 돈다.
   같음은 DataPrep/tests/test_router_js.py가 엔진과 글자까지 비교한다. */
const Router = (() => {
  const EPS = 1e-9;
  const ROUTE_KEYS = ["fast", "comfort", "safe"];

  // 파이썬 round(x, n): 정확한 십진값(toFixed(100))을 보고 딱 절반일 때만 짝수 쪽
  function pyRound(x, n) {
    if (!isFinite(x)) return x;
    const neg = x < 0 || Object.is(x, -0);
    const s = Math.abs(x).toFixed(100), dot = s.indexOf(".");
    const ip = s.slice(0, dot), fp = s.slice(dot + 1);
    const keep = fp.slice(0, n), rest = fp.slice(n);
    let up = false;
    if (rest[0] > "5") up = true;
    else if (rest[0] === "5") up = /[1-9]/.test(rest.slice(1)) || Number((n > 0 ? keep : ip).slice(-1)) % 2 === 1;
    let str = (BigInt(ip + keep) + (up ? 1n : 0n)).toString();
    if (n > 0) { str = str.padStart(n + 1, "0"); str = str.slice(0, -n) + "." + str.slice(-n); }
    const v = Number(str);
    return neg ? -v : v;
  }

  function prepare(G) {
    if (!G._idx) G._idx = new Map(G.pieces.map(p => [`${p[0]}|${p[1]}|${p[2]}`, p]));
    return G._idx;
  }

  // route_cost.effective: 길 계수 × 유형 배수 × 사람 배수
  function effective(W, route, mode, personal, keys) {
    const base = (W.routes || {})[route] || {}, mult = (W.mode_mult || {})[mode] || {}, p = personal || {};
    const out = {};
    for (const k of keys) out[k] = Number(base[k] ?? 0) * Number(mult[k] ?? 1) * Number(p[k] ?? 1);
    return out;
  }

  // route_export.personal_of: {slope, floor, road: less|normal|more} → {키: 배수}
  function personalOf(G, levels) {
    const out = {};
    for (const [g, keys] of Object.entries(G.groups)) { const m = G.levels[(levels || {})[g] || "normal"]; for (const k of keys) out[k] = m; }
    return out;
  }

  const pickTerms = (t, t0, w) => (t0 != null && !((w.cross || 0) > 0) ? t0 : t);

  // route_export.cost_from = route_cost.piece_cost와 같은 순서
  function costFrom(terms, state, length, w) {
    length = Math.abs(length);
    if (length < EPS) return [0.0, {}];
    const bd = {};
    const seq = state === "uncertain" ? terms.concat([["uncertain", 1]]) : terms;
    for (const [k, x] of seq) {
      const v = x * (w[k] || 0);
      if (v > EPS) bd[k] = (k in bd ? bd[k] : 0.0) + v;
    }
    let sum = 0;
    for (const k of Object.keys(bd)) { bd[k] = pyRound(bd[k], 6); sum += bd[k]; }
    return [length + sum, bd];
  }

  // route_engine._edges(+ _find_route_w 비용): 구간 순서대로, 출발 · 이번 도착으로만 나눔. 마디 위면 판정 없는 길이 0 연결
  function edgesFor(G, start, goal, mode, w) {
    const P = prepare(G), out = [];
    for (const [k, a, b, L] of G.segs) {
      const pts = [[0.0, a], [L, b]];
      for (const [name, sk, s] of [["S", start[0], start[1]], ["G", goal[0], goal[1]]]) {
        if (sk !== k) continue;
        const ss = Math.min(Math.max(s, 0.0), L);
        if (ss <= EPS || ss >= L - EPS) out.push({n0: name, n1: ss <= EPS ? a : b, k, s0: ss, s1: ss, st: "ok", rs: [], cf: 0.0, bf: {}, cb: 0.0, bb: {}});
        else pts.push([ss, name]);
      }
      pts.sort((x, y) => x[0] - y[0]);
      for (let i = 0; i + 1 < pts.length; i++) {
        const [s0, n0] = pts[i], [s1, n1] = pts[i + 1];
        const p = P.get(`${k}|${s0}|${s1}`);
        if (!p) throw new Error(`길 그래프에 없는 조각: ${k} ${s0} ${s1}`);
        const [st, rs] = p[3][mode];
        const [cf, bf] = costFrom(pickTerms(p[4], p[6], w), st, s1 - s0, w);
        const [cb, bb] = costFrom(pickTerms(p[5], p[7], w), st, s1 - s0, w);
        out.push({n0, n1, k, s0, s1, st, rs, cf, bf, cb, bb});
      }
    }
    return out;
  }

  // 힙: ((막힌 수, 비용), 넣은 순서) 순 — 파이썬 heapq와 같은 꺼냄 순서
  const less = (a, b) => a[0] !== b[0] ? a[0] < b[0] : a[1] !== b[1] ? a[1] < b[1] : a[2] < b[2];
  function heapPush(h, x) { h.push(x); let i = h.length - 1; while (i > 0) { const p = (i - 1) >> 1; if (!less(h[i], h[p])) break; [h[i], h[p]] = [h[p], h[i]]; i = p; } }
  function heapPop(h) {
    const top = h[0], last = h.pop();
    if (h.length) {
      h[0] = last; let i = 0;
      for (;;) { const l = 2 * i + 1, r = l + 1; let m = i; if (l < h.length && less(h[l], h[m])) m = l; if (r < h.length && less(h[r], h[m])) m = r; if (m === i) break; [h[i], h[m]] = [h[m], h[i]]; i = m; }
    }
    return top;
  }

  // route_engine._dijkstra_w
  function dijkstraW(edges, allowed, stage3) {
    const adj = new Map();
    const add = (n, x) => { let l = adj.get(n); if (!l) adj.set(n, l = []); l.push(x); };
    for (const e of edges) {
      if (!allowed.has(e.st) && !(stage3 && e.st === "blocked")) continue;
      const nb = e.st === "blocked" ? 1 : 0;
      add(e.n0, {v: e.n1, nb, c: e.cf, info: {k: e.k, s0: e.s0, s1: e.s1, e, c: e.cf}});
      add(e.n1, {v: e.n0, nb, c: e.cb, info: {k: e.k, s0: e.s1, s1: e.s0, e, c: e.cb}});
    }
    const dist = new Map([["S", [0, 0.0]]]), prev = new Map(), heap = [];
    heapPush(heap, [0, 0.0, 0, "S"]);
    let tie = 1;
    while (heap.length) {
      const [d0, d1, , u] = heapPop(heap);
      if (u === "G") break;
      const du = dist.get(u);
      if (du && (d0 > du[0] || (d0 === du[0] && d1 > du[1]))) continue;
      for (const x of adj.get(u) || []) {
        const nd0 = d0 + x.nb, nd1 = d1 + x.c, od = dist.get(x.v);
        if (od === undefined || nd0 < od[0] || (nd0 === od[0] && nd1 < od[1] - 1e-12)) {
          dist.set(x.v, [nd0, nd1]); prev.set(x.v, [u, x.info]);
          heapPush(heap, [nd0, nd1, tie, x.v]); tie++;
        }
      }
    }
    if (!dist.has("G")) return null;
    const path = [];
    for (let n = "G"; n !== "S";) { const [u, info] = prev.get(n); path.push(info); n = u; }
    return path.reverse();
  }

  // route_engine._find_route_w(앱이 쓰는 칸만)
  function findRoute(G, start, goal, mode, w) {
    const edges = edgesFor(G, start, goal, mode, w);
    let status = "ok", path = dijkstraW(edges, new Set(["ok"]), false);
    if (!path) { status = "uncertain"; path = dijkstraW(edges, new Set(["ok", "uncertain"]), false); }
    if (!path) { status = "none"; path = dijkstraW(edges, new Set(["ok", "uncertain"]), true); }
    const steps = [], raw = [];
    let total = 0.0;
    for (const x of path || []) {
      if (Math.abs(x.s1 - x.s0) < EPS) continue;
      total += x.c;
      raw.push([x.k, x.s0, x.s1, x.e.st]);
      steps.push({seg: x.k, s0: pyRound(x.s0, 3), s1: pyRound(x.s1, 3), state: x.e.st, reasons: x.e.rs});
    }
    let len = 0;
    for (const s of steps) len += Math.abs(s.s1 - s.s0);
    return {found: status !== "none", status, length_m: pyRound(len, 3), steps,
      uncertain_segs: steps.filter(s => s.state === "uncertain").length,
      blocked_by: status === "none" ? steps.filter(s => s.state === "blocked").map(s => ({seg: s.seg, reasons: s.reasons})) : [],
      cost: pyRound(total, 3), _raw: raw};
  }

  // route_engine._rescore: 길의 조각 벌점을 다른 길 계수로(길이 없이)
  function rescore(G, raw, w) {
    const P = prepare(G);
    let tot = 0.0;
    for (const [k, s0, s1, st] of raw) {
      const p = P.get(`${k}|${Math.min(s0, s1)}|${Math.max(s0, s1)}`);
      const t = s1 >= s0 ? pickTerms(p[4], p[6], w) : pickTerms(p[5], p[7], w);
      let s = 0;
      for (const v of Object.values(costFrom(t, st, s1 - s0, w)[1])) s += v;
      tot += s;
    }
    return pyRound(tot, 1);
  }

  const samePath = (a, b) => a.steps.length === b.steps.length &&
    a.steps.every((x, i) => x.seg === b.steps[i].seg && x.s0 === b.steps[i].s0 && x.s1 === b.steps[i].s1);

  // route_engine.three_routes(앱이 쓰는 칸만: overlap · breakdown · notes는 뺌)
  function three(G, goal, mode, personal) {
    prepare(G);
    const gp = G.goals[goal];
    if (!gp) throw new Error(`도착 없음: ${goal}`);
    const W = {};
    for (const rk of ROUTE_KEYS) W[rk] = effective(G.weights, rk, mode, personal, G.keys);
    const out = {};
    for (const rk of ROUTE_KEYS) out[rk] = findRoute(G, G.start, gp, mode, W[rk]);
    ROUTE_KEYS.forEach((rk, i) => {
      const r = out[rk];
      r.same_as = ROUTE_KEYS.slice(0, i).find(k => samePath(out[k], r)) || null;
      r.compare = {comfort: rescore(G, r._raw, W.comfort), safe: rescore(G, r._raw, W.safe)};
    });
    for (const r of Object.values(out)) delete r._raw;
    return out;
  }

  return {three, personalOf, pyRound, prepare, effective, costFrom};
})();
if (typeof module !== "undefined") module.exports = Router;
