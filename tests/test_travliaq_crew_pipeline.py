"""Tests unitaires pour la pipeline CrewAI de persona."""

from __future__ import annotations

import json
import json
from pathlib import Path

import pytest
import yaml

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


def test_pipeline_parses_yaml_string(tmp_path):
    payload = {
        "normalized_trip_request": {
            "trip_request_id": "tr-001",
            "user": {"user_id": "u-1", "email": None, "preferred_language": "fr"},
            "context": {
                "source_questionnaire_id": "123",
                "pipeline_run_id": None,
                "created_at": None,
                "updated_at": None,
            },
            "travel_party": {
                "group_type": "duo",
                "travelers_count": 2,
                "has_children": False,
                "children": [],
            },
            "trip_frame": {
                "origin": {"city": "Paris", "country": "France", "airport_hint": None},
                "destinations": [
                    {
                        "id": "dest-1",
                        "role": "primary",
                        "is_primary": True,
                        "order": 1,
                        "city": "Lisbonne",
                        "region": None,
                        "country": "Portugal",
                        "stay_nights": 5,
                    }
                ],
                "dates": {
                    "dates_type": "fixed",
                    "departure_date": "2024-07-01",
                    "return_date": "2024-07-06",
                    "approx_departure_date": None,
                    "flexibility_days_minus": 0,
                    "flexibility_days_plus": 0,
                    "duration_nights": 5,
                    "duration_exact": True,
                    "candidate_departure_dates": [],
                    "candidate_date_ranges": [],
                },
            },
            "budget": {
                "is_known": True,
                "currency": "EUR",
                "estimated_total_per_person": 1500,
                "estimated_total_group": 3000,
                "budget_type": "medium",
                "notes": None,
            },
            "preferences": {
                "climate": ["mild"],
                "vibe": "cosy",
                "rhythm": "balanced",
                "activities": {"tags": ["food", "art"]},
                "transport": {
                    "flight_preference": "balanced",
                    "allowed_modes_local": ["train"],
                    "baggage": {"cabin": True, "hold": False},
                },
                "accommodation": {
                    "types": ["boutique"],
                    "comfort_min_rating": 7.5,
                    "neighbourhood_style": "central",
                    "board": ["breakfast"],
                    "equipment_preferences": ["wifi"],
                },
                "time_preferences": {"needs_siesta": False, "needs_free_time": True},
            },
            "constraints": {
                "diet": {"vegetarian": True, "vegan": False, "no_pork": False, "no_alcohol": False, "other": []},
                "safety": {"special_constraints": False, "notes": None},
                "mobility": {"reduced_mobility": False, "notes": None},
                "other": [],
            },
            "assist_needed": {
                "flights": True,
                "accommodation": True,
                "activities": True,
                "other": [],
            },
            "personas": {
                "primary": {"code": "explorer", "name": "Epicurienne", "confidence": 82},
                "emerging": [],
            },
            "explanations": {
                "persona_summary": "Voyageuse flexible",
                "user_goals": ["Découvrir des restaurants"],
                "pros": ["Budget ok"],
                "cons": ["Dates à confirmer"],
                "critical_needs": ["Flexibilité"],
                "non_critical_preferences": ["Boutique hotels"],
            },
            "planning_readiness": {
                "has_fixed_destination": True,
                "has_exact_dates": True,
                "has_known_budget": True,
                "blocking_gaps": [],
            },
        },
    }

    response = yaml.safe_dump(payload, allow_unicode=True)

    pipeline = _build_pipeline_with_response(response, tmp_path)
    result = pipeline.run(questionnaire_data={"id": "123"}, persona_inference={})

    # The normalized trip agent now returns only the normalized payload; persona fields stay empty.
    assert result["persona_analysis"]["persona_summary"] == ""
    assert result["persona_analysis"]["pros"] == []
    assert result["persona_analysis"]["challenge_summary"] == ""
    assert result["persona_analysis"]["challenge_actions"] == []
    assert result["questionnaire_id"] == "123"
    assert result["normalized_trip_request"]["trip_request_id"] == "tr-001"
    assert result["persona_analysis"]["normalized_trip_request"]["trip_request_id"] == "tr-001"
    run_dir = tmp_path / result["run_id"]
    assert run_dir.exists()
    assert (run_dir / "run_output.json").exists()


def test_pipeline_still_parses_json_string(tmp_path):
    response = json.dumps({"normalized_trip_request": {"trip_request_id": "tr-123"}})

    pipeline = _build_pipeline_with_response(response, tmp_path)
    result = pipeline.run(questionnaire_data={"id": "123"}, persona_inference={})

    assert result["normalized_trip_request"]["trip_request_id"] == "tr-123"


def test_pipeline_handles_non_json_response(tmp_path):
    raw_response = "Analyse libre sans structure JSON"
    pipeline = _build_pipeline_with_response(raw_response, tmp_path)

    result = pipeline.run(questionnaire_data={}, persona_inference={})

    analysis = result["persona_analysis"]
    assert analysis["persona_summary"] == "Analyse non structurée"
    assert analysis["raw_response"] == raw_response
    assert "format structuré" in analysis["analysis_notes"]


def test_pipeline_parses_yaml_string(tmp_path):
    yaml_response = """
normalized_trip_request:
  trip_request_id: tr-yaml
  user:
    email: ami@example.com
    preferred_language: fr
  travel_party:
    group_type: friends
    travelers_count: 4
"""

    pipeline = _build_pipeline_with_response(yaml_response, tmp_path)
    result = pipeline.run(questionnaire_data={}, persona_inference={})

    normalized = result["normalized_trip_request"]
    assert normalized["trip_request_id"] == "tr-yaml"
    assert normalized["user"]["email"] == "ami@example.com"


def test_structural_enricher_enforces_origin_dates_budget(tmp_path):
    yaml_response = """
normalized_trip_request:
  travel_party:
    group_type: duo
    travelers_count: null
  trip_frame:
    origin:
      city: null
      country: null
    dates:
      type: ""
      departure_dates: []
      return_dates: []
      duration_nights: null
  budget:
    currency: null
    estimated_total_per_person: null
"""

    questionnaire = {
        "lieu_depart": "Bruxelles, Belgique",
        "type_dates": "flexible",
        "a_date_depart_approximative": "yes",
        "date_depart_approximative": "2026-01-10",
        "flexibilite": "±3j",
        "duree": "7 nuits",
        "nombre_voyageurs": 2,
        "budget_par_personne": "1 200 €",
        "budget_max_par_personne": "1 500 €",
        "devise_budget": "EUR",
    }

    pipeline = _build_pipeline_with_response(yaml_response, tmp_path)
    result = pipeline.run(questionnaire_data=questionnaire, persona_inference={})

    normalized = result["normalized_trip_request"]
    origin = normalized["trip_frame"]["origin"]
    assert origin["city"] == "Bruxelles"
    assert origin["country"] == "Belgique"

    dates = normalized["trip_frame"]["dates"]
    assert dates["type"] == "flexible"
    assert dates["range"] == {"start": "2026-01-07", "end": "2026-01-13"}
    assert dates["departure_dates"][0] == "2026-01-07"
    assert dates["departure_dates"][-1] == "2026-01-13"
    assert dates["return_dates"][0] == "2026-01-14"
    assert dates["return_dates"][-1] == "2026-01-20"
    assert dates["duration_nights"] == 7

    budget = normalized["budget"]
    assert budget["currency"] == "EUR"
    assert budget["per_person_range"] == {"min": 1200, "max": 1500}
    assert budget["group_range"]["max"] == 3000
    assert budget["estimated_total_group"] == 3000

    travel_party = normalized["travel_party"]
    assert travel_party["travelers_count"] == 2


def test_structural_enricher_uses_nested_questionnaire_payload(tmp_path):
    yaml_response = """
normalized_trip_request:
  trip_frame:
    dates:
      type: ""
  budget: {}
"""

    questionnaire = {
        "questionnaire": {
            "travel_group": "Famille",
            "number_of_travelers": "4",
            "departure_location": {"city": "Bruxelles", "country": "Belgique"},
            "dates_type": "flexible",
            "departure_window": {"start": "2026-02-01", "end": "2026-02-04"},
            "return_window": {"start": "2026-02-10", "end": "2026-02-14"},
            "budget": {
                "amount_per_person": "2 000 €",
                "amount_per_person_max": "2 500 €",
                "currency": "EUR",
            },
        }
    }

    pipeline = _build_pipeline_with_response(yaml_response, tmp_path)
    result = pipeline.run(questionnaire_data=questionnaire, persona_inference={})

    normalized = result["normalized_trip_request"]
    travel_party = normalized["travel_party"]
    assert travel_party["group_type"] == "family"
    assert travel_party["travelers_count"] == 4

    origin = normalized["trip_frame"]["origin"]
    assert origin["city"] == "Bruxelles"
    assert origin["country"] == "Belgique"


def test_trip_intent_skips_scouting_when_destination_known():
    pipeline = CrewPipeline()
    intent = pipeline._derive_trip_intent(
        {
            "has_destination": "yes",
            "destination": "Tokyo",
            "help_with": ["accommodation"],
        },
        {},
    )

    assert intent.destination_locked is True
    assert intent.should_scout is False
    assert intent.assist_flights is False
    assert intent.assist_accommodation is True
    assert intent.assist_activities is False


def test_trip_intent_defaults_to_full_scope_when_no_help_with():
    pipeline = CrewPipeline()
    intent = pipeline._derive_trip_intent(
        {"has_destination": "no"},
        {"trip_frame": {"destinations": [{"city": "Lima"}]}},
    )

    assert intent.destination_locked is False
    assert intent.should_scout is True
    assert intent.assist_flights is True
    assert intent.assist_accommodation is True
    assert intent.assist_activities is True


def test_pipeline_detects_custom_crew_builder(tmp_path):
    default_pipeline = CrewPipeline(output_dir=tmp_path)
    assert default_pipeline._use_mock_crew is False

    custom_pipeline = CrewPipeline(crew_builder=lambda **_: DummyCrew({}), output_dir=tmp_path)
    assert custom_pipeline._use_mock_crew is True

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

