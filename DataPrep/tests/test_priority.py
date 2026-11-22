"""실측 우선 구간(measure_priority.py) 시험. 민속촌 가상 자료(씨앗 7)로 본다."""
import json

import pytest

from conftest import PACK

FACS = PACK.parent.parent / "minsokchon/시설목록.geojson"


@pytest.fixture(scope="module")
def mp(ri, tmp_path_factory):
    import route_engine as R
    f = tmp_path_factory.mktemp("prio") / "경로입력.json"
    f.write_text(json.dumps(ri, ensure_ascii=False), encoding="utf-8")
    ctx, facs = R.load(f, PACK, FACS)
    return ctx, facs


def test_measured_ok_judges_ok(mp):
    import route_engine as R
    from measure_priority import measured_ok
    ctx, _ = mp
    assert R.judge(ctx.items[97], "manual").state == "blocked"  # 앞뒤 5.1~5.3°
    assert R.judge(measured_ok(ctx.items[97]), "manual").state == "ok"


def test_gate_slope_segment_frees_manual(mp):
    """구간 97(앞뒤 5.1~5.3°) 하나를 재서 문제없으면, 수동휠체어로 정문에서 97 하나에만 막힌 목적지는 모두 좋아진다
    (작업 기록 15장 나 4: 97이 막는 28곳 중 9곳은 다른 막는 구간도 있음)."""
    from measure_priority import gains, route_all
    ctx, facs = mp
    base = route_all(ctx, facs, "정문", ["manual"])
    only97 = sum(1 for r in base.values() if [b["seg"] for b in r["blocked_by"]] == [97])
    assert only97 >= 15
    assert gains(ctx, facs, "정문", ["manual"], [97], base)[97]["manual"] >= only97


def test_unused_segment_gains_nothing(mp):
    from measure_priority import gains, route_all, used_segments
    ctx, facs = mp
    base = route_all(ctx, facs, "정문", ["power"])
    used = used_segments(base)
    free = next(k for k in sorted(ctx.items) if k not in used)
    assert gains(ctx, facs, "정문", ["power"], [free], base)[free]["power"] == 0


def test_ctx_restored_and_engine_untouched(mp):
    import route_engine as R
    from measure_priority import gains
    ctx, facs = mp
    before, judge = ctx.items[97], R.judge
    gains(ctx, facs, "정문", ["manual"], [97])
    assert ctx.items[97] is before and R.judge is judge
