// router.js 시험용(Node): node router_cli.js <그래프.json> <질의.json> <결과.json>
// 질의: {goal, mode, levels} → Router.three / {personalOf: levels} / {pyRound: [x, n]}
const fs = require("fs");
const path = require("path");
const Router = require(path.join(__dirname, "router.js"));
const [, , gp, qp, op] = process.argv;
const G = JSON.parse(fs.readFileSync(gp, "utf8"));
const Q = JSON.parse(fs.readFileSync(qp, "utf8"));
const t0 = Date.now();
const out = Q.map(q => {
  if (q.pyRound !== undefined) return Router.pyRound(q.pyRound[0], q.pyRound[1]);
  if (q.personalOf !== undefined) return Router.personalOf(G, q.personalOf);
  return Router.three(G, q.goal, q.mode, Router.personalOf(G, q.levels || {}));
});
fs.writeFileSync(op, JSON.stringify(out));
const n = Q.filter(q => q.goal !== undefined).length;
if (n) console.log(`세 길 ${n}번, 한 번에 ${((Date.now() - t0) / n).toFixed(1)} ms`);
