import json

import pytest

from app.crew_pipeline import __main__ as crew_cli


@pytest.fixture(autouse=True)
def _no_logging(monkeypatch):
    monkeypatch.setattr(crew_cli, "_configure_logging", lambda level: None)


def _sample_payload() -> dict:
    return {
        "questionnaire_data": {"id": "1"},
        "persona_inference": {"persona": {"principal": "Test"}},
    }


def test_cli_runs_with_input_file(monkeypatch, tmp_path, capsys):
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(_sample_payload()))

    captured_payload = {}

    def fake_run(payload, pipeline):
        captured_payload.update(payload)
        return {
            "run_id": "demo-run",
            "status": "ok",
            "questionnaire_id": payload.get(
                "questionnaire_id", payload["questionnaire_data"].get("id", "")
            ),
            "questionnaire_data": payload["questionnaire_data"],
            "persona_inference": payload["persona_inference"],
            "persona_analysis": {
                "persona_summary": "Profil Test",
                "raw_response": "RAW",
            },
        }

    monkeypatch.setattr(crew_cli, "run_pipeline_from_payload", fake_run)

    exit_code = crew_cli.main([
        "--input-file",
        str(payload_path),
        "--log-level",
        "CRITICAL",
    ])

    assert exit_code == 0
    assert captured_payload["questionnaire_data"]["id"] == "1"

    output = capsys.readouterr().out
    assert "Profil Test" in output
    assert "RAW" not in output


def test_cli_can_include_raw(monkeypatch, tmp_path, capsys):
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(_sample_payload()))

    monkeypatch.setattr(
        crew_cli,
        "run_pipeline_from_payload",
        lambda payload, pipeline: {
            "run_id": "demo-run",
            "status": "ok",
            "questionnaire_id": payload.get(
                "questionnaire_id", payload["questionnaire_data"].get("id", "")
            ),
            "questionnaire_data": payload["questionnaire_data"],
            "persona_inference": payload["persona_inference"],
            "persona_analysis": {
                "persona_summary": "Profil",
                "raw_response": "RAW",
            },
        },
    )

    exit_code = crew_cli.main([
        "--input-file",
        str(payload_path),
        "--include-raw",
    ])

    assert exit_code == 0

    output = capsys.readouterr().out
    assert "RAW" in output


def test_cli_questionnaire_id_flow(monkeypatch, capsys):
    def fake_build(questionnaire_id: str) -> dict:
        assert questionnaire_id == "abc"
        payload = _sample_payload()
        payload["questionnaire_id"] = questionnaire_id
        return payload

    monkeypatch.setattr(crew_cli, "_build_payload_from_questionnaire", fake_build)
    monkeypatch.setattr(
        crew_cli,
        "run_pipeline_from_payload",
        lambda payload, pipeline: {
            "run_id": "demo-run",
            "status": "ok",
            "questionnaire_id": payload.get("questionnaire_id", ""),
            "questionnaire_data": payload["questionnaire_data"],
            "persona_inference": payload["persona_inference"],
            "persona_analysis": {
                "persona_summary": payload.get("questionnaire_id", ""),
            },
        },
    )

    exit_code = crew_cli.main(["--questionnaire-id", "abc"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "abc" in output
