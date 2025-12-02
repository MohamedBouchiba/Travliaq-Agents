"""Test du parsing des dates au format européen vs ISO."""
import pytest
from datetime import datetime, date

from app.crew_pipeline.scripts.normalize_questionnaire import _parse_date, normalize_questionnaire
from app.crew_pipeline.scripts.system_contract_builder import _validate_future_date


def test_parse_date_with_iso_format():
    """Format ISO (YYYY-MM-DD) doit fonctionner."""
    result, warnings = _parse_date("2025-12-15")

    assert result == "2025-12-15"
    assert len(warnings) == 0
    print(f"[OK] ISO format parsed: {result}")


def test_parse_date_with_european_format_slash():
    """Format européen DD/MM/YYYY doit maintenant fonctionner."""
    result, warnings = _parse_date("15/12/2025")

    # Maintenant, cela doit être converti en ISO
    assert result == "2025-12-15"
    assert len(warnings) == 1
    assert "convertie depuis" in warnings[0]
    print(f"[OK] European format (slash) converted: {result}, {warnings}")


def test_parse_date_with_european_format_dash():
    """Format européen DD-MM-YYYY doit maintenant fonctionner."""
    result, warnings = _parse_date("15-12-2025")

    # Maintenant, cela doit être converti en ISO
    assert result == "2025-12-15"
    assert len(warnings) == 1
    assert "convertie depuis" in warnings[0]
    print(f"[OK] European format (dash) converted: {result}, {warnings}")


def test_ambiguous_date_01_10_2025():
    """Date ambiguë : 01/10/2025 = 1er octobre (EU) ou 10 janvier (US) ?"""
    # Maintenant parsée comme format européen (prioritaire)
    result, warnings = _parse_date("01/10/2025")

    # Parsée comme 1er octobre (format EU prioritaire)
    assert result == "2025-10-01"
    assert "convertie depuis" in warnings[0]
    print(f"[INFO] Ambiguous date parsed as EU format: {result} (October 1st)")


def test_full_questionnaire_with_european_dates():
    """Test complet : questionnaire avec dates européennes."""
    questionnaire = {
        "id": "test-123",
        "date_depart": "15/12/2025",  # Format européen
        "date_retour": "22/12/2025",
        "nombre_voyageurs": 2,
    }

    result = normalize_questionnaire(questionnaire)

    # Les dates doivent maintenant être converties en ISO
    assert result['questionnaire']['date_depart'] == "2025-12-15"
    assert result['questionnaire']['date_retour'] == "2025-12-22"

    # Il devrait y avoir des warnings de conversion
    warnings = result['metadata']['warnings']
    assert len(warnings) >= 2
    assert any("convertie depuis" in w for w in warnings)

    print(f"[OK] European dates converted to ISO")
    print(f"Warnings: {warnings}")


def test_what_happens_after_normalization():
    """Que se passe-t-il quand les dates européennes sont normalisées ?"""
    questionnaire = {
        "id": "test-456",
        "date_depart": "15/12/2025",  # Maintenant converti en ISO
        "nuits_exactes": 7,
    }

    # 1. Normalisation
    normalized = normalize_questionnaire(questionnaire)

    # 2. System Contract Builder (avec dates converties)
    from app.crew_pipeline.scripts.system_contract_builder import build_system_contract

    contract = build_system_contract(
        questionnaire=normalized['questionnaire'],
        normalized_trip_request={},
        persona_context={}
    )

    # Les dates doivent être présentes en format ISO
    departure_dates = contract['timing']['departure_dates_whitelist']
    return_dates = contract['timing']['return_dates_whitelist']

    assert len(departure_dates) == 1
    assert departure_dates[0] == "2025-12-15"
    assert return_dates == []  # Pas fournie

    print("[OK] After normalization, dates are correctly in ISO format")
    print(f"Departure dates: {departure_dates}")
    print(f"Return dates: {return_dates}")


def test_proposed_solution_parse_european_dates():
    """Solution proposée : parser multiple formats."""

    def parse_date_flexible(date_str: str | None) -> str | None:
        """Parse multiple date formats: ISO, EU slash, EU dash."""
        if not date_str:
            return None

        # Liste des formats à essayer
        formats = [
            "%Y-%m-%d",      # ISO: 2025-12-15
            "%d/%m/%Y",      # EU slash: 15/12/2025
            "%d-%m-%Y",      # EU dash: 15-12-2025
            "%Y/%m/%d",      # ISO slash: 2025/12/15
            "%m/%d/%Y",      # US slash: 12/15/2025 (ambiguous)
        ]

        for fmt in formats:
            try:
                parsed = datetime.strptime(date_str, fmt)
                return parsed.date().isoformat()
            except ValueError:
                continue

        # Si aucun format ne fonctionne
        return None

    # Tests
    assert parse_date_flexible("2025-12-15") == "2025-12-15"  # ISO
    assert parse_date_flexible("15/12/2025") == "2025-12-15"  # EU slash
    assert parse_date_flexible("15-12-2025") == "2025-12-15"  # EU dash
    assert parse_date_flexible("2025/12/15") == "2025-12-15"  # ISO slash

    print("[OK] Flexible parser works for all formats")

    # Cas ambigus
    result = parse_date_flexible("01/10/2025")
    # Ce sera parsé comme 1er octobre (format EU essayé en premier)
    assert result == "2025-10-01"
    print(f"[INFO] Ambiguous date 01/10/2025 parsed as: {result} (October 1st)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
