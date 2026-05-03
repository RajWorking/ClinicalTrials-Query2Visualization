import json

from scripts import smoke_analyze


def test_smoke_analyze_write_flag_updates_response_file(monkeypatch, tmp_path):
    (tmp_path / "case.request.json").write_text('{"query":"trials by phase"}')
    body = {
        "visualization": {
            "type": "bar_chart",
            "data": [{"phase": "Phase 1", "trial_count": 1}],
        },
        "meta": {"total_studies_matched": 1, "truncated": False},
    }

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return body

    class FakeClient:
        def __init__(self, _app):
            pass

        def post(self, _path, json):
            return FakeResponse()

    monkeypatch.setattr(smoke_analyze, "CASES", [("case", "bar_chart")])
    monkeypatch.setattr(smoke_analyze, "EXAMPLES", tmp_path)
    monkeypatch.setattr(smoke_analyze, "TestClient", FakeClient)

    assert smoke_analyze.run_cases(write=True) == 0
    written = json.loads((tmp_path / "case.response.json").read_text())
    assert written == body
