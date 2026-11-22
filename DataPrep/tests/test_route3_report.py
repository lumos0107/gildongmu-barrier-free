"""가중치 경로 Task 5: 결과 보고(route3_report.summarize). 가짜 결과로 센다."""
from route3_report import summarize


def r1(status):
    return {"status": status, "blocked_by": [], "steps": []}


def route(status, length, same_as=None, overlap=None, bd=None, blocked=()):
    return {"status": status, "length_m": length, "same_as": same_as, "overlap": overlap or {},
            "breakdown": bd or {}, "blocked_by": [{"seg": 1, "reasons": list(blocked)}] if blocked else []}


def r3(fast, comfort, safe, entry="ok"):
    return {"routes": {"fast": fast, "comfort": comfort, "safe": safe}, "entry": {"state": entry}}


def test_counts_and_changed():
    legacy = {("A", "manual"): r1("ok"), ("B", "manual"): r1("uncertain")}
    new = {("A", "manual"): r3(route("ok", 10), route("ok", 10, "fast"), route("ok", 10, "fast")),
           ("B", "manual"): r3(route("none", 20, blocked=["연석경사로 8.2°"]), route("none", 20, "fast"),
                               route("none", 20, "fast"), entry="blocked")}
    s = summarize(legacy, new)
    assert s["legacy_counts"]["manual"] == {"ok": 1, "uncertain": 1, "none": 0}
    assert s["counts"]["fast"]["manual"] == {"ok": 1, "uncertain": 0, "none": 1}
    assert s["changed"] == [["B", "manual", "uncertain", "none", ["연석경사로 8.2°"]]]
    assert s["entry"]["manual"] == {"ok": 1, "blocked": 1}


def test_same_zero_only_when_no_penalty():
    legacy = {("A", "power"): r1("ok"), ("B", "power"): r1("ok")}
    new = {("A", "power"): r3(route("ok", 10), route("ok", 10, "fast"), route("ok", 10, "fast")),
           ("B", "power"): r3(route("ok", 10), route("ok", 10, "fast", bd={"long": 3.0}), route("ok", 10, "fast"))}
    s = summarize(legacy, new)
    assert s["differ"]["power"]["all_same"] == 2 and s["same_zero"]["power"] == 1


def test_differ_and_demo():
    o = {"comfort": 0.5, "safe": 0.3, "fast": 0.5}
    new = {("A", "stroller"): r3(route("ok", 100, overlap={"comfort": 0.5, "safe": 0.3}),
                                 route("ok", 130, overlap={"fast": 0.5, "safe": 0.6}),
                                 route("ok", 125, overlap={"fast": 0.3, "comfort": 0.6})),
           ("B", "stroller"): r3(route("ok", 100), route("ok", 101, overlap=o), route("ok", 100, "fast"))}
    s = summarize({k: r1("ok") for k in new}, new)
    d = s["differ"]["stroller"]
    assert d == {"all_same": 0, "any_diff": 2, "len20": 1}
    assert [x["to"] for x in s["demo"]] == ["A"] and s["demo"][0]["mode"] == "stroller"


def test_changed_uncertain_reasons():
    legacy = {("A", "power"): r1("ok")}
    fast = route("uncertain", 10) | {"steps": [{"state": "ok", "reasons": []},
                                              {"state": "uncertain", "reasons": ["연석경사로 끝 턱 20 mm"]}]}
    new = {("A", "power"): r3(fast, route("uncertain", 10, "fast"), route("uncertain", 10, "fast"))}
    assert summarize(legacy, new)["changed"] == [["A", "power", "ok", "uncertain", ["연석경사로 끝 턱 20 mm"]]]
