"""
Code prêt à copier-coller pour implémenter les validations de dates
Auteur: Claude Code
Date: 2025-12-02
"""

from datetime import date, datetime
from functools import wraps
from typing import Any, Dict, Optional


# =============================================================================
# 1. CORRECTION POUR: app/crew_pipeline/scripts/system_contract_builder.py
# =============================================================================

def _validate_future_date(date_str: str | None) -> str | None:
    """
    Valide qu'une date est dans le futur, sinon la corrige automatiquement.

    Args:
        date_str: Date au format ISO (YYYY-MM-DD) ou None

    Returns:
        - Date corrigée si elle était passée
        - Date originale si elle est future
        - None si invalide ou None

    Exemples:
        >>> _validate_future_date("2023-12-01")
        "2025-12-01"  # Corrigée (aujourd'hui = 2025-12-02)

        >>> _validate_future_date("2026-06-15")
        "2026-06-15"  # Déjà future, pas de modification

        >>> _validate_future_date(None)
        None  # Géré proprement
    """
    if not date_str:
        return None

    try:
        date_obj = datetime.fromisoformat(date_str).date()
        today = date.today()

        if date_obj < today:
            # Calculer combien d'années ajouter pour revenir dans le futur
            years_to_add = 1
            while date_obj.replace(year=date_obj.year + years_to_add) < today:
                years_to_add += 1

            corrected_date = date_obj.replace(year=date_obj.year + years_to_add)

            # Log optionnel (recommandé pour monitoring)
            # logger.warning(
            #     f"Date passée corrigée: {date_str} → {corrected_date.isoformat()} "
            #     f"(+{years_to_add} an(s))"
            # )

            return corrected_date.isoformat()

        return date_str

    except (ValueError, AttributeError):
        # Date invalide, on retourne None plutôt que de crasher
        # logger.error(f"Format de date invalide: {date_str}")
        return None


def build_system_contract_CORRECTED(
    *,
    questionnaire: Dict[str, Any],
    normalized_trip_request: Dict[str, Any],
    persona_context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Version CORRIGÉE de build_system_contract avec validation des dates.

    MODIFICATION: Les dates sont maintenant validées AVANT d'être ajoutées au contrat.
    """

    request_meta = {
        "request_id": questionnaire.get("id") or questionnaire.get("questionnaire_id"),
        "user_id": questionnaire.get("user_id"),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source_version": "crew_pipeline_v2",
    }

    user_intelligence = {
        "email": questionnaire.get("email"),
        "narrative_summary": persona_context.get("narrative") or persona_context.get("persona") or "",
        "feasibility_status": "PENDING",
        "feasibility_alerts": [],
    }

    # ✅ CORRECTION: Validation des dates AVANT ajout au contrat
    raw_departure = questionnaire.get("date_depart")
    raw_return = questionnaire.get("date_retour")

    validated_departure = _validate_future_date(raw_departure)
    validated_return = _validate_future_date(raw_return)

    timing = {
        "request_type": questionnaire.get("type_dates") or "flexible",
        "duration_min_nights": normalized_trip_request.get("nuits_exactes") or questionnaire.get("nuits_exactes"),
        "duration_max_nights": normalized_trip_request.get("nuits_exactes") or questionnaire.get("nuits_exactes"),
        # ✅ UTILISATION DES DATES VALIDÉES
        "departure_dates_whitelist": [validated_departure] if validated_departure else [],
        "return_dates_whitelist": [validated_return] if validated_return else [],
    }

    # Optionnel: Tracer les corrections pour debugging
    if raw_departure and validated_departure and raw_departure != validated_departure:
        timing["_corrections"] = timing.get("_corrections", [])
        timing["_corrections"].append({
            "field": "departure",
            "original": raw_departure,
            "corrected": validated_departure
        })

    if raw_return and validated_return and raw_return != validated_return:
        timing["_corrections"] = timing.get("_corrections", [])
        timing["_corrections"].append({
            "field": "return",
            "original": raw_return,
            "corrected": validated_return
        })

    geography = {
        "origin_city": questionnaire.get("lieu_depart"),
        "destination_is_defined": questionnaire.get("a_destination") == "yes",
        "destination_city": questionnaire.get("destination"),
        "destination_country": None,
        "discovery_climate_zones": [],
        "discovery_regions": [],
        "excluded_tags": questionnaire.get("contraintes") or [],
    }

    financials = {
        "currency": "EUR",
        "total_hard_cap": None,
        "total_soft_cap": None,
        "budget_range_input": questionnaire.get("budget_par_personne"),
    }

    specifications = {
        "flights": {
            "cabin_class": "ECONOMY",
            "luggage_policy": questionnaire.get("bagages"),
            "stopover_tolerance": "AUTO",
            "preference": questionnaire.get("preference_vol"),
        },
        "accommodation": {
            "types_allowed": questionnaire.get("type_hebergement") or [],
            "min_rating_10": None,
            "required_amenities": questionnaire.get("equipements") or [],
            "location_vibe": questionnaire.get("quartier"),
            "comfort": questionnaire.get("confort"),
        },
        "experience": {
            "pace": questionnaire.get("rythme"),
            "interest_vectors": questionnaire.get("styles") or [],
            "constraints": questionnaire.get("contraintes") or [],
            "safety": questionnaire.get("securite") or [],
        },
    }

    return {
        "meta": request_meta,
        "user_intelligence": user_intelligence,
        "timing": timing,
        "geography": geography,
        "financials": financials,
        "specifications": specifications,
    }


# =============================================================================
# 2. CORRECTION POUR: app/crew_pipeline/mcp_tools.py
# =============================================================================

def validate_date_params(func):
    """
    Décorateur qui valide les paramètres de date AVANT l'exécution de l'outil MCP.

    Vérifie que toutes les dates sont:
    - Au format ISO valide (YYYY-MM-DD)
    - Dans le futur (>= aujourd'hui)

    Lance une ValueError avec message explicite si validation échoue.

    Usage:
        @validate_date_params
        def flights_prices_tool(origin: str, destination: str, departure: str, **kwargs):
            # ... code existant
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        today = date.today()

        # Liste des paramètres de date à valider
        date_params = [
            'checkin',
            'checkout',
            'departure',
            'return_date',
            'date',
            'departure_date',
            'return',
        ]

        for param in date_params:
            if param in kwargs:
                date_str = kwargs[param]

                if not date_str:
                    continue  # Paramètre optionnel non fourni

                # Validation du format
                try:
                    date_obj = datetime.fromisoformat(date_str).date()
                except (ValueError, AttributeError) as e:
                    raise ValueError(
                        f"❌ Format de date invalide pour '{param}': {date_str}\n"
                        f"Format attendu: YYYY-MM-DD (exemple: 2025-12-15)\n"
                        f"Erreur: {e}"
                    ) from e

                # Validation date future
                if date_obj < today:
                    raise ValueError(
                        f"❌ Date passée détectée pour '{param}': {date_str}\n"
                        f"Les voyages ne peuvent être planifiés que dans le futur.\n"
                        f"Date minimum: {today.isoformat()}\n"
                        f"💡 Suggestion: Consulte system_contract.timing.departure_dates_whitelist "
                        f"pour les dates validées."
                    )

        # Si toutes les validations passent, exécuter la fonction
        return func(*args, **kwargs)

    return wrapper


# EXEMPLE D'APPLICATION
@validate_date_params
def flights_prices_tool_EXAMPLE(
    origin: str,
    destination: str,
    departure: str,
    return_date: Optional[str] = None,
    **kwargs
):
    """
    Outil MCP pour récupérer les prix de vols.

    ✅ Maintenant protégé par @validate_date_params
    Les dates sont validées AVANT l'appel à l'API externe.
    """
    # Code existant...
    pass


@validate_date_params
def booking_search_tool_EXAMPLE(
    city: str,
    checkin: str,
    checkout: str,
    adults: int = 2,
    **kwargs
):
    """
    Outil MCP pour rechercher des hôtels sur Booking.com.

    ✅ Maintenant protégé par @validate_date_params
    """
    # Code existant...
    pass


# =============================================================================
# 3. AMÉLIORATION OPTIONNELLE: Feedback Loop avec Correction Auto
# =============================================================================

def validate_and_correct_date_params(func):
    """
    Version AMÉLIORÉE du décorateur qui CORRIGE automatiquement au lieu de crasher.

    Retourne un message d'erreur constructif avec la date corrigée si date passée.
    L'agent peut alors réessayer avec la bonne date.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        today = date.today()
        date_params = ['checkin', 'checkout', 'departure', 'return_date', 'date']

        corrections = {}

        for param in date_params:
            if param not in kwargs or not kwargs[param]:
                continue

            date_str = kwargs[param]

            try:
                date_obj = datetime.fromisoformat(date_str).date()
            except (ValueError, AttributeError):
                return {
                    "error": f"Format de date invalide pour '{param}': {date_str}",
                    "expected_format": "YYYY-MM-DD",
                    "example": "2025-12-15"
                }

            if date_obj < today:
                # Calculer date corrigée
                years_to_add = 1
                while date_obj.replace(year=date_obj.year + years_to_add) < today:
                    years_to_add += 1
                corrected = date_obj.replace(year=date_obj.year + years_to_add).isoformat()

                corrections[param] = {
                    "original": date_str,
                    "corrected": corrected
                }

        # Si corrections nécessaires, retourner message explicatif
        if corrections:
            return {
                "error": "Dates passées détectées",
                "corrections_required": corrections,
                "message": (
                    "Les dates fournies sont dans le passé et ne sont plus disponibles. "
                    "Utilise les dates corrigées ci-dessus pour obtenir les résultats."
                ),
                "contract_reference": "system_contract.timing.departure_dates_whitelist"
            }

        # Si tout est OK, exécuter normalement
        return func(*args, **kwargs)

    return wrapper


# =============================================================================
# 4. TESTS UNITAIRES PRÊTS À L'EMPLOI
# =============================================================================

def test_validate_future_date():
    """Test de la fonction _validate_future_date()."""
    from datetime import timedelta

    # Test: Date passée → Corrigée
    past_date = (date.today() - timedelta(days=365)).isoformat()
    result = _validate_future_date(past_date)
    assert result is not None
    assert date.fromisoformat(result) >= date.today()

    # Test: Date future → Inchangée
    future_date = (date.today() + timedelta(days=30)).isoformat()
    result = _validate_future_date(future_date)
    assert result == future_date

    # Test: None → None
    result = _validate_future_date(None)
    assert result is None

    # Test: Date invalide → None
    result = _validate_future_date("invalid-date")
    assert result is None

    print("[OK] Tous les tests _validate_future_date() passent!")


def test_validate_date_params_decorator():
    """Test du décorateur @validate_date_params."""
    from datetime import timedelta

    @validate_date_params
    def mock_tool(departure: str, **kwargs):
        return f"Appel réussi avec {departure}"

    # Test: Date future → OK
    future = (date.today() + timedelta(days=30)).isoformat()
    result = mock_tool(departure=future)
    assert "Appel réussi" in result

    # Test: Date passée → ValueError
    past = (date.today() - timedelta(days=30)).isoformat()
    try:
        mock_tool(departure=past)
        assert False, "Devrait lever ValueError"
    except ValueError as e:
        assert "Date passée détectée" in str(e)

    # Test: Format invalide → ValueError
    try:
        mock_tool(departure="invalid-date")
        assert False, "Devrait lever ValueError"
    except ValueError as e:
        assert "Format de date invalide" in str(e)

    print("[OK] Tous les tests du decorateur passent!")


# =============================================================================
# MAIN: Exécuter les tests
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("TESTS DE VALIDATION DES DATES")
    print("=" * 60)

    test_validate_future_date()
    test_validate_date_params_decorator()

    print("\n" + "=" * 60)
    print("[OK] TOUS LES TESTS PASSENT")
    print("=" * 60)
    print("\nCode pret a etre integre dans votre pipeline!")
