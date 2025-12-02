"""Test que les dates validées sont correctement injectées dans les prompts des agents."""
import pytest
from datetime import date

from app.crew_pipeline.scripts.system_contract_builder import build_system_contract


def test_dates_are_extracted_from_contract():
    """Vérifie que les dates du contract peuvent être extraites et formatées."""
    # Questionnaire avec date passée (doit être corrigée)
    questionnaire = {
        "id": "test-123",
        "date_depart": "2023-10-01",
        "date_retour": "2023-10-08",
        "nuits_exactes": 7,
    }

    # Construire le contract (avec validation automatique)
    contract = build_system_contract(
        questionnaire=questionnaire,
        normalized_trip_request={},
        persona_context={}
    )

    # Extraire les dates (comme dans pipeline.py)
    departure_dates = contract.get("timing", {}).get("departure_dates_whitelist", [])
    return_dates = contract.get("timing", {}).get("return_dates_whitelist", [])

    # Vérifier que les dates existent
    assert len(departure_dates) == 1
    assert len(return_dates) == 1

    # Vérifier que les dates sont futures
    departure_date = date.fromisoformat(departure_dates[0])
    return_date = date.fromisoformat(return_dates[0])

    today = date.today()
    assert departure_date >= today, f"Departure {departure_date} doit être >= {today}"
    assert return_date >= today, f"Return {return_date} doit être >= {today}"

    # Formatter comme dans pipeline.py
    departure_dates_str = ", ".join([d for d in departure_dates if d])
    return_dates_str = ", ".join([d for d in return_dates if d])

    # Vérifier que le format est correct
    assert departure_dates_str != "Non spécifiées"
    assert return_dates_str != "Non spécifiées"

    print(f"[OK] Dates de depart injectees: {departure_dates_str}")
    print(f"[OK] Dates de retour injectees: {return_dates_str}")


def test_prompt_with_injected_dates():
    """Simule comment un agent verrait les dates dans son prompt."""
    questionnaire = {
        "id": "test-456",
        "date_depart": "2024-06-15",
        "nuits_exactes": 7,
    }

    contract = build_system_contract(
        questionnaire=questionnaire,
        normalized_trip_request={},
        persona_context={}
    )

    # Extraction
    departure_dates = contract.get("timing", {}).get("departure_dates_whitelist", [])
    return_dates = contract.get("timing", {}).get("return_dates_whitelist", [])

    departure_dates_str = ", ".join([d for d in departure_dates if d]) if departure_dates else "Non spécifiées"
    return_dates_str = ", ".join([d for d in return_dates if d]) if return_dates else "Non spécifiées"

    # Simuler le prompt de l'agent (comme dans tasks.yaml)
    prompt = f"""
    Estime les hébergements pour Honolulu.

    **DATES VALIDÉES À UTILISER** :
    - Dates de check-in : {departure_dates_str}
    - Dates de check-out : {return_dates_str}

    **RÈGLE CRITIQUE** : Utilise UNIQUEMENT ces dates validées ci-dessus.
    """

    # Vérifier que le prompt contient les bonnes dates
    assert "2024-06-15" not in prompt, "Date originale ne doit pas apparaître"
    # Note: return_dates peut être "Non spécifiées" car on n'a pas fourni date_retour
    assert departure_dates_str != "Non spécifiées", "Date de départ doit être définie"

    # Vérifier qu'une date future apparaît
    today = date.today()
    if departure_dates:
        corrected_date = date.fromisoformat(departure_dates[0])
        assert corrected_date >= today
        assert str(corrected_date.year) in prompt
        assert corrected_date.year >= 2025

    print("[OK] Prompt contient les dates corrigees:")
    print(prompt)


def test_no_dates_in_questionnaire():
    """Vérifie le comportement quand aucune date n'est fournie."""
    questionnaire = {
        "id": "test-no-dates",
        "destination": "Paris",
    }

    contract = build_system_contract(
        questionnaire=questionnaire,
        normalized_trip_request={},
        persona_context={}
    )

    departure_dates = contract.get("timing", {}).get("departure_dates_whitelist", [])
    return_dates = contract.get("timing", {}).get("return_dates_whitelist", [])

    # Formatter
    departure_dates_str = ", ".join([d for d in departure_dates if d]) if departure_dates else "Non spécifiées"
    return_dates_str = ", ".join([d for d in return_dates if d]) if return_dates else "Non spécifiées"

    # Vérifier que c'est bien marqué comme non spécifié
    assert departure_dates_str == "Non spécifiées"
    assert return_dates_str == "Non spécifiées"

    print("[OK] Comportement correct quand dates absentes")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
