"""Tests unitaires pour la pipeline CrewAI de persona."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.crew_pipeline import run_pipeline_from_payload
from app.crew_pipeline import pipeline as pipeline_module
from app.crew_pipeline.pipeline import CrewPipeline


class DummyCrew:
    """Crew factice permettant de simuler les réponses de CrewAI."""

    def __init__(self, response):
        self.response = response
        self.inputs = None

    def kickoff(self, inputs):  # pragma: no cover - simple délégation
        self.inputs = inputs
        return self.response


class DummyCrewOutput:
    """Objet imitant CrewOutput pour tester la persistance."""

    def __init__(self, *, raw: str, json_dict: dict | None = None, tasks_output=None):
        self.raw = raw
        self.json_dict = json_dict
        self.tasks_output = tasks_output or []


class DummyTaskOutput:
    """Version simplifiée de TaskOutput pour les tests."""

    def __init__(
        self,
        *,
        name: str,
        raw: str,
        agent: str = "agent",
        description: str = "desc",
        json_dict: dict | None = None,
        expected_output: str | None = None,
    ) -> None:
        self.name = name
        self.raw = raw
        self.agent = agent
        self.description = description
        self.json_dict = json_dict
        self.expected_output = expected_output


def _build_pipeline_with_response(response, tmp_path: Path):
    return CrewPipeline(crew_builder=lambda **_: DummyCrew(response), output_dir=tmp_path)


def test_pipeline_parses_json_string(tmp_path):
    response = json.dumps(
        {
            "persona_summary": "Voyageuse flexible",
            "pros": ["Budget confortable"],
            "cons": ["Incertitude sur les dates"],
            "critical_needs": ["Flexibilité du planning"],
            "non_critical_preferences": ["Hôtels design"],
            "user_goals": ["Vivre une expérience culinaire"],
            "narrative": "Une exploratrice urbaine en quête de découvertes.",
            "analysis_notes": "Profil cohérent avec les données du questionnaire.",
            "challenge_summary": "Challenge validé",
            "challenge_actions": ["Insister sur la flexibilité des transferts"],
        }
    )

    pipeline = _build_pipeline_with_response(response, tmp_path)
    result = pipeline.run(questionnaire_data={"id": "123"}, persona_inference={})

    assert result["persona_analysis"]["persona_summary"] == "Voyageuse flexible"
    assert "Budget confortable" in result["persona_analysis"]["pros"]
    assert result["persona_analysis"]["challenge_summary"] == "Challenge validé"
    assert "Insister sur la flexibilité" in result["persona_analysis"]["challenge_actions"][0]
    assert result["questionnaire_id"] == "123"
    run_dir = tmp_path / result["run_id"]
    assert run_dir.exists()
    assert (run_dir / "run_output.json").exists()


def test_pipeline_handles_non_json_response(tmp_path):
    raw_response = "Analyse libre sans structure JSON"
    pipeline = _build_pipeline_with_response(raw_response, tmp_path)

    result = pipeline.run(questionnaire_data={}, persona_inference={})

    analysis = result["persona_analysis"]
    assert analysis["persona_summary"] == "Analyse non structurée"
    assert analysis["raw_response"] == raw_response
    assert "format JSON" in analysis["analysis_notes"]


def test_pipeline_passes_inputs_to_crew(tmp_path):
    dummy = DummyCrew({})
    pipeline = CrewPipeline(crew_builder=lambda **_: dummy, output_dir=tmp_path)

    questionnaire = {"foo": "bar"}
    inference = {"persona": {"principal": "Aventurier"}}

    pipeline.run(questionnaire_data=questionnaire, persona_inference=inference)

    assert dummy.inputs["questionnaire"] == questionnaire
    assert dummy.inputs["persona_context"] == inference
    assert "input_payload" in dummy.inputs


def test_pipeline_persists_task_outputs(tmp_path):
    task_output = DummyTaskOutput(
        name="traveller_profile_brief",
        raw=json.dumps({"persona_summary": "ok"}),
        json_dict={"persona_summary": "ok"},
        expected_output="{}",
    )
    crew_output = DummyCrewOutput(
        raw=json.dumps({"persona_summary": "ok"}),
        json_dict={"persona_summary": "ok"},
        tasks_output=[task_output],
    )

    pipeline = _build_pipeline_with_response(crew_output, tmp_path)
    result = pipeline.run(
        questionnaire_data={"id": "abc"},
        persona_inference={"persona": {}},
    )

    run_dir = tmp_path / result["run_id"]
    task_file = run_dir / "tasks" / "traveller_profile_brief.json"
    assert task_file.exists()
    saved = json.loads(task_file.read_text(encoding="utf-8"))
    assert saved["task_name"] == "traveller_profile_brief"
    assert saved["json_output"]["persona_summary"] == "ok"


def test_run_pipeline_from_payload_requires_questionnaire(tmp_path):
    with pytest.raises(ValueError):
        run_pipeline_from_payload(
            {"persona_inference": {}},
            pipeline=CrewPipeline(crew_builder=lambda **_: DummyCrew({}), output_dir=tmp_path),
        )


def test_run_pipeline_from_payload_uses_provided_pipeline(tmp_path):
    expected = {"status": "ok"}

    class DummyPipeline(CrewPipeline):  # pragma: no cover - ensures type compatibility
        def run(self, **kwargs):
            return expected

    payload = {
        "questionnaire_data": {"id": "1"},
        "persona_inference": {"persona": {}},
    }

    result = run_pipeline_from_payload(
        payload,
        pipeline=DummyPipeline(crew_builder=lambda **_: DummyCrew({}), output_dir=tmp_path),
    )

    assert result == expected


def test_placeholder_api_key_allows_env_override(monkeypatch):
    monkeypatch.setattr(
        pipeline_module.settings,
        "openai_api_key",
        "your_key_here",
        raising=False,
    )
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value")
    monkeypatch.setenv("MODEL", "gpt-unit-test")

    captured: dict[str, dict[str, object]] = {}

    def fake_llm(**kwargs):
        captured["kwargs"] = kwargs

        class DummyLLM:  # pragma: no cover - simple conteneur
            pass

        return DummyLLM()

    monkeypatch.setattr(pipeline_module, "LLM", fake_llm)

    pipeline_module._build_default_llm()

    assert captured["kwargs"]["api_key"] == "sk-test-value"


@pytest.mark.parametrize(
    "candidate,expected",
    [
        ("your_key_here", None),
        ("  your_key*here  ", None),
        ("changeme", None),
        ("", None),
        (None, None),
        ("sk-live-123", "sk-live-123"),
    ],
)
def test_pick_first_secret_filters_placeholders(candidate, expected):
    other = "sk-env-456"
    if expected is None and candidate is not None:
        assert (
            pipeline_module._pick_first_secret(candidate, other)
            == (other if other else None)
        )
    else:
        assert pipeline_module._pick_first_secret(candidate) == expected

