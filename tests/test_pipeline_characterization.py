"""
Tests de caractérisation : capturer le comportement ACTUEL de la pipeline
pour détecter les régressions pendant le refactoring.

Ces tests ne vérifient PAS le comportement idéal, mais capturent
le comportement RÉEL actuel pour le comparer après refactoring.
"""
import json
import os
from pathlib import Path
from typing import Dict, Any

import pytest

# Fixtures avec vrais questionnaires de test
QUESTIONNAIRE_RELAXED = {
    "id": "test-relaxed-001",
    "destination": "Paris, France",
    "has_destination": "yes",
    "duree": "7",
    "date_depart": "2025-06-01",
    "rythme": "relaxed",
    "nombre_voyageurs": 2,
    "budget_par_personne": 1500,
    "devise_budget": "EUR",
    "lieu_depart": "Bruxelles, Belgique",
    "help_with": ["flights", "accommodation", "activities"],
    "affinites_voyage": ["culture", "gastronomie"]
}

QUESTIONNAIRE_BALANCED = {
    "id": "test-balanced-001",
    "destination": "Tokyo, Japan",
    "has_destination": "yes",
    "duree": "10",
    "date_depart": "2025-07-01",
    "rythme": "balanced",
    "nombre_voyageurs": 2,
    "budget_par_personne": 2000,
    "devise_budget": "EUR",
    "lieu_depart": "Paris, France",
    "help_with": ["flights", "accommodation", "activities"],
    "affinites_voyage": ["culture", "nature"]
}

QUESTIONNAIRE_INTENSE = {
    "id": "test-intense-001",
    "destination": "New York, USA",
    "has_destination": "yes",
    "duree": "5",
    "date_depart": "2025-08-01",
    "rythme": "intense",
    "nombre_voyageurs": 2,
    "budget_par_personne": 2500,
    "devise_budget": "EUR",
    "lieu_depart": "Londres, UK",
    "help_with": ["flights", "accommodation", "activities"],
    "affinites_voyage": ["culture", "shopping", "gastronomie"]
}

PERSONA_INFERENCE = {
    "persona_label": "Explorateur Culturel",
    "persona_score": 0.85,
    "persona_description": "Voyageur passionné de culture et d'histoire"
}


class TestPipelineCharacterization:
    """Capture le comportement actuel pour détecter régressions."""

    @pytest.fixture
    def snapshots_dir(self):
        """Répertoire pour sauvegarder les snapshots."""
        dir_path = Path(__file__).parent / "snapshots"
        dir_path.mkdir(exist_ok=True)
        return dir_path

    def test_incremental_builder_structure_initialization(self):
        """Test que IncrementalTripBuilder initialise la structure correctement."""
        from app.crew_pipeline.scripts.incremental_trip_builder import IncrementalTripBuilder

        builder = IncrementalTripBuilder(QUESTIONNAIRE_RELAXED)
        builder.initialize_structure(
            destination="Paris",
            destination_en="Paris",
            start_date="2025-06-01",
            rhythm="relaxed",
            mcp_tools=[]
        )

        # Caractérisation : vérifier structure actuelle
        assert "code" in builder.trip_json
        assert "destination" in builder.trip_json
        assert "steps" in builder.trip_json
        assert isinstance(builder.trip_json["steps"], list)

        # Vérifier nombre de steps (relaxed: 7 jours × 1.5 = 10.5 → 10 steps)
        activity_steps = [s for s in builder.trip_json["steps"] if not s.get("is_summary")]
        assert len(activity_steps) == 10, f"Expected 10 activity steps for relaxed 7 days, got {len(activity_steps)}"

        # Vérifier summary step
        summary_steps = [s for s in builder.trip_json["steps"] if s.get("is_summary")]
        assert len(summary_steps) == 1, f"Expected 1 summary step, got {len(summary_steps)}"
        assert summary_steps[0]["step_number"] == 99

        # Snapshot de la structure
        structure_keys = sorted(builder.trip_json.keys())
        expected_keys = [
            'average_weather', 'code', 'destination', 'destination_en',
            'flight_duration', 'flight_from', 'flight_to', 'flight_type',
            'hotel_name', 'hotel_rating', 'main_image', 'price_activities',
            'price_flights', 'price_hotels', 'price_transport', 'start_date',
            'steps', 'total_budget', 'total_days', 'total_price',
            'travel_style', 'travel_style_en', 'travelers'
        ]
        assert structure_keys == expected_keys, f"Structure keys changed! Expected {expected_keys}, got {structure_keys}"

    def test_step_count_calculation_relaxed(self):
        """Test que le calcul de steps pour relaxed est cohérent."""
        from app.crew_pipeline.scripts.incremental_trip_builder import IncrementalTripBuilder

        builder = IncrementalTripBuilder({"duree": "7", "nombre_voyageurs": 2})
        num_steps = builder._calculate_steps_count(7, "relaxed")

        # Caractérisation actuelle : relaxed = 1.5 × jours
        assert num_steps == 10, f"Expected 10 steps for 7 days relaxed, got {num_steps}"

    def test_step_count_calculation_balanced(self):
        """Test que le calcul de steps pour balanced est cohérent."""
        from app.crew_pipeline.scripts.incremental_trip_builder import IncrementalTripBuilder

        builder = IncrementalTripBuilder({"duree": "10", "nombre_voyageurs": 2})
        num_steps = builder._calculate_steps_count(10, "balanced")

        # Caractérisation actuelle : balanced = 1.5 × jours
        assert num_steps == 15, f"Expected 15 steps for 10 days balanced, got {num_steps}"

    def test_step_count_calculation_intense(self):
        """Test que le calcul de steps pour intense est cohérent."""
        from app.crew_pipeline.scripts.incremental_trip_builder import IncrementalTripBuilder

        builder = IncrementalTripBuilder({"duree": "5", "nombre_voyageurs": 2})
        num_steps = builder._calculate_steps_count(5, "intense")

        # Caractérisation actuelle : intense = 2.5 × jours
        assert num_steps == 12, f"Expected 12 steps for 5 days intense, got {num_steps}"

    def test_builder_set_step_title_modifies_in_place(self):
        """Test que set_step_title modifie bien la step."""
        from app.crew_pipeline.scripts.incremental_trip_builder import IncrementalTripBuilder

        builder = IncrementalTripBuilder(QUESTIONNAIRE_RELAXED)
        builder.initialize_structure("Paris", "Paris", "2025-06-01", "relaxed", [])

        # Modifier une step
        builder.set_step_title(1, "Tour Eiffel", "Eiffel Tower", "Visite guidée", "Guided tour")

        # Vérifier modification
        step = builder._get_step(1)
        assert step is not None
        assert step["title"] == "Tour Eiffel"
        assert step["title_en"] == "Eiffel Tower"
        assert step["subtitle"] == "Visite guidée"
        assert step["subtitle_en"] == "Guided tour"

    def test_builder_get_json_returns_valid_structure(self):
        """Test que get_json retourne une structure valide."""
        from app.crew_pipeline.scripts.incremental_trip_builder import IncrementalTripBuilder

        builder = IncrementalTripBuilder(QUESTIONNAIRE_RELAXED)
        builder.initialize_structure("Paris", "Paris", "2025-06-01", "relaxed", [])

        trip_json = builder.get_json()

        # Vérifier structure
        assert isinstance(trip_json, dict)
        assert "code" in trip_json
        assert "destination" in trip_json
        assert "steps" in trip_json
        assert len(trip_json["steps"]) == 11  # 10 activity + 1 summary

    def test_normalization_preserves_essential_fields(self):
        """Test que la normalisation préserve les champs essentiels."""
        from app.crew_pipeline.scripts import normalize_questionnaire

        result = normalize_questionnaire(QUESTIONNAIRE_RELAXED)

        assert "questionnaire" in result
        normalized = result["questionnaire"]

        # Vérifier champs préservés
        assert normalized.get("duree") == "7"
        assert normalized.get("rythme") == "relaxed"
        assert normalized.get("nombre_voyageurs") == 2
        assert normalized.get("destination") == "Paris, France"

    def test_trip_code_format(self):
        """Test que le format du code trip est cohérent."""
        from app.crew_pipeline.scripts.incremental_trip_builder import IncrementalTripBuilder

        builder = IncrementalTripBuilder(QUESTIONNAIRE_RELAXED)
        builder.initialize_structure("Paris", "Paris", "2025-06-01", "relaxed", [])

        code = builder.trip_json["code"]

        # Caractérisation : code = DESTINATION-YEAR-UUID
        import re
        pattern = r'^[A-Z0-9]+-\d{4}-[A-F0-9]{6}$'
        assert re.match(pattern, code), f"Code format changed! Got: {code}"

    def test_summary_step_has_required_fields(self):
        """Test que la summary step a tous les champs requis."""
        from app.crew_pipeline.scripts.incremental_trip_builder import IncrementalTripBuilder

        builder = IncrementalTripBuilder(QUESTIONNAIRE_RELAXED)
        builder.initialize_structure("Paris", "Paris", "2025-06-01", "relaxed", [])

        summary = [s for s in builder.trip_json["steps"] if s.get("is_summary")][0]

        # Vérifier champs requis
        assert summary["step_number"] == 99
        assert summary["day_number"] == 0
        assert summary["is_summary"] is True
        assert summary["step_type"] == "summary"
        assert "summary_stats" in summary
        assert isinstance(summary["summary_stats"], list)

    def test_completeness_report_structure(self):
        """Test que le rapport de complétude a la bonne structure."""
        from app.crew_pipeline.scripts.incremental_trip_builder import IncrementalTripBuilder

        builder = IncrementalTripBuilder(QUESTIONNAIRE_RELAXED)
        builder.initialize_structure("Paris", "Paris", "2025-06-01", "relaxed", [])

        report = builder.get_completeness_report()

        # Vérifier structure du rapport
        assert "trip_completeness" in report
        assert "steps_with_title" in report
        assert "steps_with_image" in report
        assert "steps_with_gps" in report
        assert "missing_critical" in report

    @pytest.mark.skip(reason="Requires actual pipeline execution - too slow for quick tests")
    def test_full_pipeline_execution_snapshot(self, snapshots_dir):
        """
        Test d'exécution complète de la pipeline (SLOW).

        Sauvegarde un snapshot du résultat pour comparaison future.
        Skipped par défaut car lent (MCP calls, LLM calls).
        """
        from app.crew_pipeline import travliaq_crew_pipeline

        result = travliaq_crew_pipeline.run(
            questionnaire_data=QUESTIONNAIRE_RELAXED,
            persona_inference=PERSONA_INFERENCE
        )

        # Sauvegarder snapshot
        snapshot_file = snapshots_dir / "relaxed_pipeline_result.json"
        with open(snapshot_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        # Vérifications basiques
        assert result["status"] in ["success", "failed_validation"]
        assert "assembly" in result
        assert "trip" in result["assembly"]


class TestStepCountConsistency:
    """Tests spécifiques pour cohérence calcul nombre de steps."""

    def test_step_count_matches_between_builder_and_config(self):
        """Test que le calcul de steps est cohérent entre builder et config."""
        from app.crew_pipeline.scripts.incremental_trip_builder import IncrementalTripBuilder

        # Test tous les rythmes
        test_cases = [
            (7, "relaxed", 10),   # 7 × 1.5 = 10.5 → 10
            (7, "balanced", 10),  # 7 × 1.5 = 10.5 → 10
            (7, "intense", 17),   # 7 × 2.5 = 17.5 → 17
            (10, "relaxed", 15),  # 10 × 1.5 = 15
            (10, "balanced", 15), # 10 × 1.5 = 15
            (10, "intense", 25),  # 10 × 2.5 = 25
        ]

        builder = IncrementalTripBuilder({"nombre_voyageurs": 2})

        for days, rhythm, expected in test_cases:
            actual = builder._calculate_steps_count(days, rhythm)
            assert actual == expected, f"Mismatch for {days} days {rhythm}: expected {expected}, got {actual}"
