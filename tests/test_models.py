"""Tests unitaires pour les modèles Pydantic de la pipeline CrewAI."""

import pytest
from pydantic import ValidationError

from app.crew_pipeline.models import (
    PersonaAnalysisOutput,
    PersonaChallengeOutput,
    TripSpecificationsOutput,
    PipelineMetrics,
    DestinationInfo,
    DateInfo,
)


class TestPersonaAnalysisOutput:
    """Tests pour PersonaAnalysisOutput."""
    
    def test_valid_output(self):
        """Test avec des données valides."""
        data = {
            "persona_summary": "Voyageur aventurier",
            "pros": ["Budget flexible", "Expérience voyage"],
            "cons": ["Temps limité"],
            "critical_needs": ["Vols directs"],
            "non_critical_preferences": ["Cuisine locale"],
            "user_goals": ["Découverte culturelle"],
            "narrative": "Jean est un voyageur curieux qui recherche l'authenticité...",
            "analysis_notes": "Profil bien défini",
        }
        
        output = PersonaAnalysisOutput(**data)
        assert output.persona_summary == "Voyageur aventurier"
        assert len(output.pros) == 2
        assert len(output.cons) == 1
    
    def test_minimum_required_fields(self):
        """Test avec seulement les champs requis."""
        data = {
            "persona_summary": "Profil test",
            "narrative": "Un narratif suffisamment long pour passer la validation minimale.",
        }
        
        output = PersonaAnalysisOutput(**data)
        assert output.persona_summary == "Profil test"
        assert output.pros == []
        assert output.cons == []
    
    def test_narrative_too_short(self):
        """Test avec un narratif trop court."""
        data = {
            "persona_summary": "Profil test",
            "narrative": "Court",  # Moins de 50 caractères
        }
        
        with pytest.raises(ValidationError) as exc_info:
            PersonaAnalysisOutput(**data)
        
        errors = exc_info.value.errors()
        assert any("narrative" in str(err) for err in errors)
    
    def test_summary_too_short(self):
        """Test avec un summary trop court."""
        data = {
            "persona_summary": "Court",  # Moins de 10 caractères
            "narrative": "Un narratif suffisamment long pour passer la validation.",
        }
        
        with pytest.raises(ValidationError) as exc_info:
            PersonaAnalysisOutput(**data)
        
        errors = exc_info.value.errors()
        assert any("persona_summary" in str(err) for err in errors)


class TestPersonaChallengeOutput:
    """Tests pour PersonaChallengeOutput."""
    
    def test_valid_output(self):
        """Test avec des données valides."""
        data = {
            "persona_summary": "Voyageur aventurier validé",
            "pros": ["Budget confirmé"],
            "cons": ["Contraintes familiales"],
            "critical_needs": ["Assurance"],
            "non_critical_preferences": ["Guide francophone"],
            "user_goals": ["Immersion"],
            "narrative": "Jean est un voyageur expérimenté cherchant l'authenticité...",
            "analysis_notes": "Analyse validée",
            "challenge_summary": "Validation avec ajustements mineurs",
            "challenge_actions": ["Proposer guide local"],
        }
        
        output = PersonaChallengeOutput(**data)
        assert output.challenge_summary == "Validation avec ajustements mineurs"
        assert len(output.challenge_actions) == 1
    
    def test_missing_challenge_summary(self):
        """Test sans challenge_summary (requis)."""
        data = {
            "persona_summary": "Profil validé",
            "narrative": "Un narratif suffisamment long pour la validation...",
            # challenge_summary manquant
        }
        
        with pytest.raises(ValidationError) as exc_info:
            PersonaChallengeOutput(**data)
        
        errors = exc_info.value.errors()
        assert any("challenge_summary" in str(err) for err in errors)


class TestTripSpecificationsOutput:
    """Tests pour TripSpecificationsOutput."""
    
    def test_valid_output(self):
        """Test avec des données valides."""
        data = {
            "normalized_trip_request": {
                "user": {
                    "email": "test@example.com",
                    "preferred_language": "fr"
                },
                "travel_party": {
                    "group_type": "couple",
                    "travelers_count": 2
                }
            },
            "synthesis_notes": "Données complètes",
        }
        
        output = TripSpecificationsOutput(**data)
        assert output.normalized_trip_request["user"]["email"] == "test@example.com"
        assert output.synthesis_notes == "Données complètes"
    
    def test_empty_normalized_trip(self):
        """Test avec normalized_trip_request vide."""
        data = {
            "normalized_trip_request": {},
        }
        
        output = TripSpecificationsOutput(**data)
        assert output.normalized_trip_request == {}
        assert output.synthesis_notes == ""


class TestDestinationInfo:
    """Tests pour DestinationInfo."""
    
    def test_valid_destination(self):
        """Test avec une destination valide."""
        data = {
            "label": "primary",
            "city": "Tokyo",
            "country": "Japan",
            "stay_nights": 7,
        }
        
        dest = DestinationInfo(**data)
        assert dest.label == "primary"
        assert dest.city == "Tokyo"
        assert dest.stay_nights == 7
    
    def test_negative_nights(self):
        """Test avec un nombre de nuits négatif."""
        data = {
            "label": "primary",
            "city": "Paris",
            "stay_nights": -1,
        }
        
        with pytest.raises(ValidationError) as exc_info:
            DestinationInfo(**data)
        
        errors = exc_info.value.errors()
        assert any("stay_nights" in str(err) for err in errors)


class TestDateInfo:
    """Tests pour DateInfo."""
    
    def test_fixed_dates(self):
        """Test avec des dates fixes."""
        data = {
            "type": "fixed",
            "departure_dates": ["2024-06-01"],
            "return_dates": ["2024-06-15"],
            "duration_nights": 14,
        }
        
        dates = DateInfo(**data)
        assert dates.type == "fixed"
        assert len(dates.departure_dates) == 1
        assert dates.duration_nights == 14
    
    def test_flexible_dates(self):
        """Test avec des dates flexibles."""
        data = {
            "type": "flexible",
            "departure_dates": ["2024-06-01", "2024-06-02", "2024-06-03"],
            "return_dates": ["2024-06-15", "2024-06-16"],
        }
        
        dates = DateInfo(**data)
        assert dates.type == "flexible"
        assert len(dates.departure_dates) == 3
    
    def test_invalid_type(self):
        """Test avec un type invalide."""
        data = {
            "type": "maybe",  # Doit être "fixed" ou "flexible"
            "departure_dates": ["2024-06-01"],
        }
        
        with pytest.raises(ValidationError) as exc_info:
            DateInfo(**data)
        
        errors = exc_info.value.errors()
        assert any("type" in str(err) for err in errors)


class TestPipelineMetrics:
    """Tests pour PipelineMetrics."""
    
    def test_valid_metrics(self):
        """Test avec des métriques valides."""
        data = {
            "run_id": "test-run-123",
            "total_duration_seconds": 45.67,
            "agent_executions": [
                {
                    "agent": "analyst",
                    "duration": 20.5,
                }
            ],
            "total_tokens_used": 1500,
            "estimated_cost_usd": 0.0045,
            "errors_count": 0,
            "warnings_count": 1,
        }
        
        metrics = PipelineMetrics(**data)
        assert metrics.run_id == "test-run-123"
        assert metrics.total_tokens_used == 1500
        assert metrics.errors_count == 0
    
    def test_negative_duration(self):
        """Test avec une durée négative."""
        data = {
            "run_id": "test-run",
            "total_duration_seconds": -10.0,  # Invalide
        }
        
        with pytest.raises(ValidationError) as exc_info:
            PipelineMetrics(**data)
        
        errors = exc_info.value.errors()
        assert any("total_duration_seconds" in str(err) for err in errors)
    
    def test_negative_tokens(self):
        """Test avec un nombre de tokens négatif."""
        data = {
            "run_id": "test-run",
            "total_duration_seconds": 10.0,
            "total_tokens_used": -100,  # Invalide
        }
        
        with pytest.raises(ValidationError) as exc_info:
            PipelineMetrics(**data)
        
        errors = exc_info.value.errors()
        assert any("total_tokens_used" in str(err) for err in errors)
