"""세 길 기준 저장·비교(B단계 Task 1) 시험."""
import json

import pytest

import three_compare as TC


def test_html_routes_reads_embedded_data(tmp_path):
    d = {"w": 1, "routes": {"가|manual": {"three": {"fast": {"len": 3}}}}, "graph": {"segs": []}}
    p = tmp_path / "a.html"
    p.write_text("<script>\nconst D = " + json.dumps(d, ensure_ascii=False, separators=(",", ":"))
                 + ";\nconst MODES = {a: 1};\nfunction f() { return {}; }\n</script>", encoding="utf-8")
    assert TC.html_routes(p) == d["routes"]


def test_compare_reports_difference():
    a = {"x|manual": {"s": 1}, "y|manual": {"s": 2}}
    b = {"x|manual": {"s": 1}, "y|manual": {"s": 3}, "z|power": {}}
    assert TC.diff_keys(a, b) == ["y|manual", "z|power"]
    assert TC.diff_keys(a, a) == []


def test_save_refuses_overwrite(tmp_path):
    p = tmp_path / "기준.json"
    TC.save_json(p, {"a": 1})
    with pytest.raises(FileExistsError):
        TC.save_json(p, {"a": 2})
    TC.save_json(p, {"a": 2}, force=True)
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 2}
