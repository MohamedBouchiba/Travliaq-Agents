"""Tests de validation des dates dans la pipeline Travliaq."""

import pytest
from datetime import date, timedelta, datetime

from app.crew_pipeline.scripts.system_contract_builder import _validate_future_date, build_system_contract
from app.crew_pipeline.trip_structural_enricher import enrich_trip_structural_data


class TestValidateFutureDate:
    """Tests de la fonction _validate_future_date()."""

    def test_past_date_is_corrected(self):
        """Les dates passées doivent être automatiquement corrigées."""
        past_date = (date.today() - timedelta(days=365)).isoformat()
        result = _validate_future_date(past_date)

        assert result is not None
        result_date = date.fromisoformat(result)
        assert result_date >= date.today(), f"Date doit être future: {result_date} >= {date.today()}"

    def test_future_date_unchanged(self):
        """Les dates déjà futures ne doivent pas être modifiées."""
        future_date = (date.today() + timedelta(days=30)).isoformat()
        result = _validate_future_date(future_date)

        assert result == future_date

    def test_none_returns_none(self):
        """None doit retourner None."""
        result = _validate_future_date(None)
        assert result is None

    def test_invalid_date_returns_none(self):
        """Une date invalide doit retourner None."""
        result = _validate_future_date("invalid-date")
        assert result is None

    def test_empty_string_returns_none(self):
        """Une chaîne vide doit retourner None."""
        result = _validate_future_date("")
        assert result is None

    def test_very_old_date_corrected(self):
        """Une date très ancienne (2000) doit être corrigée."""
        old_date = "2000-01-01"
        result = _validate_future_date(old_date)

        assert result is not None
        result_date = date.fromisoformat(result)
        assert result_date >= date.today()
        # La date devrait être en 2025 ou après
        assert result_date.year >= 2025


class TestSystemContractBuilder:
    """Tests de build_system_contract avec validation des dates."""

    def test_past_departure_date_corrected_in_contract(self):
        """Les dates de départ passées doivent être corrigées dans le contrat."""
        questionnaire = {
            "id": "test-123",
            "date_depart": "2023-12-01",
            "nuits_exactes": 7,
        }

        contract = build_system_contract(
            questionnaire=questionnaire,
            normalized_trip_request={},
            persona_context={}
        )

        whitelist = contract['timing']['departure_dates_whitelist']
        assert len(whitelist) == 1
        assert whitelist[0] is not None

        departure_date = date.fromisoformat(whitelist[0])
        assert departure_date >= date.today(), "Contract ne doit PAS contenir de dates passées"

        # Vérifier que la correction est tracée
        assert '_date_corrections' in contract['timing']
        corrections = contract['timing']['_date_corrections']
        assert len(corrections) == 1
        assert corrections[0]['field'] == 'departure'
        assert corrections[0]['original'] == "2023-12-01"

    def test_past_return_date_corrected_in_contract(self):
        """Les dates de retour passées doivent être corrigées."""
        questionnaire = {
            "id": "test-456",
            "date_depart": (date.today() + timedelta(days=30)).isoformat(),
            "date_retour": "2024-06-15",
        }

        contract = build_system_contract(
            questionnaire=questionnaire,
            normalized_trip_request={},
            persona_context={}
        )

        return_whitelist = contract['timing']['return_dates_whitelist']
        assert len(return_whitelist) == 1

        return_date = date.fromisoformat(return_whitelist[0])
        assert return_date >= date.today()

    def test_future_dates_not_modified_in_contract(self):
        """Les dates futures ne doivent pas être modifiées."""
        future_departure = (date.today() + timedelta(days=30)).isoformat()
        future_return = (date.today() + timedelta(days=37)).isoformat()

        questionnaire = {
            "id": "test-789",
            "date_depart": future_departure,
            "date_retour": future_return,
        }

        contract = build_system_contract(
            questionnaire=questionnaire,
            normalized_trip_request={},
            persona_context={}
        )

        assert contract['timing']['departure_dates_whitelist'][0] == future_departure
        assert contract['timing']['return_dates_whitelist'][0] == future_return
        assert '_date_corrections' not in contract['timing']

    def test_no_dates_in_questionnaire(self):
        """Pas de crash si le questionnaire ne contient pas de dates."""
        questionnaire = {
            "id": "test-no-dates",
            "destination": "Paris",
        }

        contract = build_system_contract(
            questionnaire=questionnaire,
            normalized_trip_request={},
            persona_context={}
        )

        assert contract['timing']['departure_dates_whitelist'] == []
        assert contract['timing']['return_dates_whitelist'] == []


class TestTripStructuralEnricher:
    """Tests de enrich_trip_structural_data."""

    def test_past_absolute_dates_are_corrected(self):
        """Les dates passées absolues doivent être corrigées."""
        questionnaire = {
            "date_depart": "2023-12-01",
            "date_retour": "2023-12-15",
            "nuits_exactes": 14
        }

        result = enrich_trip_structural_data({}, questionnaire)
        dates = result.get('trip_frame', {}).get('dates', {})

        # Vérifier que les dates sont dans le futur
        today = date.today()
        departure_str = dates['departure_dates'][0]
        departure = date.fromisoformat(departure_str)

        assert departure >= today, f"Date de départ doit être future: {departure} >= {today}"
        assert 'original_dates_detected' in dates, "Les dates originales doivent être conservées"
        assert dates['original_dates_detected']['departure'] == ["2023-12-01"]

    def test_no_dates_generates_next_season(self):
        """En l'absence de dates, un créneau 'Next Season' doit être généré."""
        questionnaire = {"destination": "Paris"}

        result = enrich_trip_structural_data({}, questionnaire)
        dates = result.get('trip_frame', {}).get('dates', {})

        assert 'departure_dates' in dates
        assert dates.get('note') == "Dates générées par défaut (Next Season)"

        # Vérifier que c'est bien J+90
        departure = date.fromisoformat(dates['departure_dates'][0])
        expected = date.today() + timedelta(days=90)
        assert abs((departure - expected).days) <= 1  # Tolérance 1 jour

    def test_future_dates_not_modified(self):
        """Les dates déjà futures ne doivent pas être modifiées."""
        future_date = (date.today() + timedelta(days=30)).isoformat()
        questionnaire = {
            "date_depart": future_date,
            "nuits_exactes": 7
        }

        result = enrich_trip_structural_data({}, questionnaire)
        dates = result.get('trip_frame', {}).get('dates', {})

        assert dates['departure_dates'][0] == future_date
        assert 'original_dates_detected' not in dates  # Pas de correction nécessaire

    def test_flexible_dates_with_past_approx_date(self):
        """Dates flexibles avec date approximative passée."""
        questionnaire = {
            "date_depart_approximative": "2023-12-01",
            "flexibilite": 3,
            "duree": 7
        }

        result = enrich_trip_structural_data({}, questionnaire)
        dates = result.get('trip_frame', {}).get('dates', {})

        # Toutes les dates générées doivent être futures
        for date_str in dates.get('departure_dates', []):
            departure = date.fromisoformat(date_str)
            assert departure >= date.today(), f"Date flexible doit être future: {departure}"


class TestMCPToolsDateValidation:
    """Tests du décorateur validate_date_params."""

    def test_validate_date_params_with_future_date(self):
        """Le décorateur doit accepter les dates futures."""
        from app.crew_pipeline.mcp_tools import validate_date_params

        @validate_date_params
        def mock_tool(departure: str, **kwargs):
            return f"Success: {departure}"

        future = (date.today() + timedelta(days=30)).isoformat()
        result = mock_tool(departure=future)

        assert "Success" in result
        assert future in result

    def test_validate_date_params_rejects_past_date(self):
        """Le décorateur doit rejeter les dates passées."""
        from app.crew_pipeline.mcp_tools import validate_date_params

        @validate_date_params
        def mock_tool(departure: str, **kwargs):
            return f"Success: {departure}"

        past = (date.today() - timedelta(days=30)).isoformat()

        with pytest.raises(ValueError) as exc_info:
            mock_tool(departure=past)

        assert "Date passée détectée" in str(exc_info.value)
        assert past in str(exc_info.value)

    def test_validate_date_params_rejects_invalid_format(self):
        """Le décorateur doit rejeter les formats invalides."""
        from app.crew_pipeline.mcp_tools import validate_date_params

        @validate_date_params
        def mock_tool(checkin: str, **kwargs):
            return f"Success: {checkin}"

        with pytest.raises(ValueError) as exc_info:
            mock_tool(checkin="invalid-date")

        assert "Format de date invalide" in str(exc_info.value)

    def test_validate_date_params_handles_multiple_date_params(self):
        """Le décorateur doit valider plusieurs paramètres de date."""
        from app.crew_pipeline.mcp_tools import validate_date_params

        @validate_date_params
        def mock_tool(checkin: str, checkout: str, **kwargs):
            return f"Success: {checkin} to {checkout}"

        future_checkin = (date.today() + timedelta(days=30)).isoformat()
        future_checkout = (date.today() + timedelta(days=37)).isoformat()

        result = mock_tool(checkin=future_checkin, checkout=future_checkout)
        assert "Success" in result

    def test_validate_date_params_with_none_date(self):
        """Le décorateur doit accepter None pour les paramètres optionnels."""
        from app.crew_pipeline.mcp_tools import validate_date_params

        @validate_date_params
        def mock_tool(departure: str, return_date: str = None, **kwargs):
            return f"Success: {departure}"

        future = (date.today() + timedelta(days=30)).isoformat()
        result = mock_tool(departure=future, return_date=None)

        assert "Success" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
