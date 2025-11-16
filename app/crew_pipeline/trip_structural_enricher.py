"""Post-traitements déterministes sur le JSON normalisé du voyage."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

_NUMBER_PATTERN = re.compile(r"-?\d+(?:[.,]\d+)?")
_DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")


@dataclass
class BudgetSignals:
    """Structure interne conservant les bornes budgétaires détectées."""

    per_person_min: Optional[float] = None
    per_person_max: Optional[float] = None
    total_min: Optional[float] = None
    total_max: Optional[float] = None
    currency: Optional[str] = None


def enrich_trip_structural_data(
    normalized_trip_request: Optional[Dict[str, Any]],
    questionnaire_data: Mapping[str, Any],
) -> Dict[str, Any]:
    """Renforce les champs structurants via les données du questionnaire."""

    if not isinstance(normalized_trip_request, dict):
        normalized_trip_request = {}

    safe_questionnaire: Dict[str, Any]
    if isinstance(questionnaire_data, Mapping):
        safe_questionnaire = dict(questionnaire_data)
    else:  # pragma: no cover - garde-fou supplémentaire
        safe_questionnaire = {}

    enriched = deepcopy(normalized_trip_request)

    travel_party = enriched.setdefault("travel_party", {})
    travellers_count = _ensure_travel_party_size(travel_party, safe_questionnaire)

    _ensure_origin(enriched, safe_questionnaire)
    _ensure_dates(enriched, safe_questionnaire)
    _ensure_budget(enriched, safe_questionnaire, travellers_count)

    return enriched


def _ensure_travel_party_size(
    travel_party: Dict[str, Any], questionnaire: Mapping[str, Any]
) -> Optional[int]:
    """Garantit que le nombre de voyageurs est renseigné."""

    current = _to_int(travel_party.get("travelers_count"))
    if current is not None and current > 0:
        travel_party["travelers_count"] = current
        return current

    candidates = [
        "nombre_voyageurs",
        "nb_voyageurs",
        "nombre_personnes",
        "travelers_count",
        "nb_people",
        "nb_personnes",
    ]
    for key in candidates:
        value = questionnaire.get(key)
        parsed = _to_int(value)
        if parsed is not None and parsed > 0:
            travel_party["travelers_count"] = parsed
            return parsed

    return current


def _ensure_origin(enriched: Dict[str, Any], questionnaire: Mapping[str, Any]) -> None:
    """Renseigne systématiquement la ville/pays d'origine."""

    trip_frame = enriched.setdefault("trip_frame", {})
    origin = trip_frame.setdefault("origin", {})

    city = origin.get("city")
    country = origin.get("country")

    city_candidates = [
        questionnaire.get("origin_city"),
        questionnaire.get("ville_depart"),
        questionnaire.get("depart_city"),
        questionnaire.get("depart_ville"),
    ]
    country_candidates = [
        questionnaire.get("origin_country"),
        questionnaire.get("pays_depart"),
        questionnaire.get("depart_country"),
        questionnaire.get("depart_pays"),
    ]

    combined = questionnaire.get("lieu_depart")
    if combined:
        extracted_city, extracted_country = _split_city_country(str(combined))
        if extracted_city and not city:
            city = extracted_city
        if extracted_country and not country:
            country = extracted_country

    for candidate in city_candidates:
        if candidate and not city:
            city = str(candidate).strip()
    for candidate in country_candidates:
        if candidate and not country:
            country = str(candidate).strip()

    origin["city"] = city or None
    origin["country"] = country or None


def _ensure_dates(enriched: Dict[str, Any], questionnaire: Mapping[str, Any]) -> None:
    """Normalise les dates de départ/retour et les ranges flexibles."""

    trip_frame = enriched.setdefault("trip_frame", {})
    dates = trip_frame.setdefault("dates", {})

    duration = _extract_duration(dates, questionnaire)

    type_hint = str(dates.get("type") or "").lower()
    questionnaire_type = str(questionnaire.get("type_dates") or "").lower()
    approx_flag = str(questionnaire.get("a_date_depart_approximative") or "").lower()
    flex_days = _parse_flex_days(questionnaire.get("flexibilite"))
    approx_date = _parse_date(questionnaire.get("date_depart_approximative"))

    is_flexible = any(
        value in {"flexible", "flex", "yes", "true", "1"}
        for value in (type_hint, questionnaire_type, approx_flag)
    )
    if flex_days is not None and flex_days > 0:
        is_flexible = True

    departure_dates: List[str] = []
    return_dates: List[str] = []

    if is_flexible and approx_date and flex_days is not None:
        departure_dates = _build_flexible_dates(approx_date, flex_days)
        dates["type"] = "flexible"
        if duration:
            return_dates = _shift_dates(departure_dates, duration)
            dates["duration_nights"] = duration
        if departure_dates:
            dates["range"] = {
                "start": departure_dates[0],
                "end": departure_dates[-1],
            }
    else:
        departure = _parse_date(questionnaire.get("date_depart"))
        if departure:
            departure_dates = [_isoformat(departure)]
        else:
            departure_dates = _ensure_str_list(dates.get("departure_dates"))

        retour = _parse_date(questionnaire.get("date_retour"))
        if retour:
            return_dates = [_isoformat(retour)]
        elif departure and duration:
            return_dates = [_isoformat(departure + timedelta(days=duration))]
        else:
            return_dates = _ensure_str_list(dates.get("return_dates"))

        if not dates.get("type"):
            dates["type"] = "fixed"
        if duration and not dates.get("duration_nights"):
            dates["duration_nights"] = duration
        dates.pop("range", None)

    if not return_dates and duration and departure_dates:
        return_dates = _shift_dates(departure_dates, duration)

    if departure_dates:
        dates["departure_dates"] = departure_dates
    if return_dates:
        dates["return_dates"] = return_dates


def _ensure_budget(
    enriched: Dict[str, Any],
    questionnaire: Mapping[str, Any],
    travelers: Optional[int],
) -> None:
    """Extrait des bornes budgétaires fiables et calcule le total groupe."""

    budget = enriched.setdefault("budget", {})
    signals = _collect_budget_signals(budget, questionnaire)

    if signals.currency:
        budget["currency"] = signals.currency

    per_person_min = signals.per_person_min
    per_person_max = signals.per_person_max

    if per_person_min is not None and per_person_max is None:
        per_person_max = per_person_min
    if per_person_max is not None and per_person_min is None:
        per_person_min = per_person_max
    if (
        per_person_min is not None
        and per_person_max is not None
        and per_person_min > per_person_max
    ):
        per_person_min, per_person_max = per_person_max, per_person_min

    if per_person_min is not None or per_person_max is not None:
        budget["per_person_range"] = {
            "min": _normalize_amount(per_person_min),
            "max": _normalize_amount(per_person_max),
        }

    total_min = signals.total_min
    total_max = signals.total_max

    if total_min is not None and total_max is None:
        total_max = total_min
    if total_max is not None and total_min is None:
        total_min = total_max
    if total_min is not None and total_max is not None and total_min > total_max:
        total_min, total_max = total_max, total_min

    if travelers and per_person_min is not None and total_min is None:
        total_min = per_person_min * travelers
    if travelers and per_person_max is not None and total_max is None:
        total_max = per_person_max * travelers

    if total_min is not None or total_max is not None:
        budget["group_range"] = {
            "min": _normalize_amount(total_min),
            "max": _normalize_amount(total_max),
        }

    reference_per_person = _to_float(budget.get("estimated_total_per_person"))
    if reference_per_person is None:
        reference_per_person = per_person_max or per_person_min
        if reference_per_person is not None:
            budget["estimated_total_per_person"] = _normalize_amount(
                reference_per_person
            )

    if reference_per_person is not None and travelers:
        budget["estimated_total_group"] = _normalize_amount(
            reference_per_person * travelers
        )


def _extract_duration(
    dates: Dict[str, Any], questionnaire: Mapping[str, Any]
) -> Optional[int]:
    """Retourne la durée en nuits en cherchant dans toutes les sources."""

    duration = _to_int(dates.get("duration_nights"))
    if duration:
        return duration

    for key in ("duree", "nuits_exactes", "duree_nuits"):
        value = questionnaire.get(key)
        if value is None:
            continue
        if isinstance(value, (int, float)):
            duration = int(value)
        else:
            numbers = _extract_numbers(value)
            if numbers:
                duration = int(numbers[0])
        if duration:
            return duration
    return None


def _collect_budget_signals(
    budget_section: Mapping[str, Any], questionnaire: Mapping[str, Any]
) -> BudgetSignals:
    """Agrège toutes les informations budgétaires disponibles."""

    signals = BudgetSignals()

    # Récupère l'éventuelle devise déjà fixée
    currency_candidates = [
        budget_section.get("currency"),
        questionnaire.get("devise_budget"),
        questionnaire.get("currency"),
        questionnaire.get("currency_budget"),
    ]
    for candidate in currency_candidates:
        if candidate:
            signals.currency = str(candidate).strip()
            break

    def _ingest_range(
        current_min: Optional[float],
        current_max: Optional[float],
        values: Iterable[float],
        *,
        prefer_min: bool = False,
        prefer_max: bool = False,
    ) -> Tuple[Optional[float], Optional[float]]:
        vals = list(values)
        if not vals:
            return current_min, current_max
        local_min = min(vals)
        local_max = max(vals)
        if prefer_min:
            local_max = local_min
        if prefer_max:
            local_min = local_max
        current_min = local_min if current_min is None else min(current_min, local_min)
        current_max = local_max if current_max is None else max(current_max, local_max)
        return current_min, current_max

    per_person_range = budget_section.get("per_person_range")
    if isinstance(per_person_range, Mapping):
        signals.per_person_min = _to_float(per_person_range.get("min"))
        signals.per_person_max = _to_float(per_person_range.get("max"))

    group_range = budget_section.get("group_range")
    if isinstance(group_range, Mapping):
        signals.total_min = _to_float(group_range.get("min"))
        signals.total_max = _to_float(group_range.get("max"))

    est_person = _to_float(budget_section.get("estimated_total_per_person"))
    if est_person is not None:
        signals.per_person_min, signals.per_person_max = _ingest_range(
            signals.per_person_min, signals.per_person_max, [est_person]
        )

    est_group = _to_float(budget_section.get("estimated_total_group"))
    if est_group is not None:
        signals.total_min, signals.total_max = _ingest_range(
            signals.total_min, signals.total_max, [est_group]
        )

    for key, value in questionnaire.items():
        if not isinstance(key, str):
            continue
        normalized_key = key.lower()
        if "budget" not in normalized_key and "price" not in normalized_key:
            continue
        numbers = _extract_numbers(value)
        if not numbers:
            continue
        prefer_min = "min" in normalized_key
        prefer_max = "max" in normalized_key
        target_person = "person" in normalized_key or "personne" in normalized_key

        if target_person:
            signals.per_person_min, signals.per_person_max = _ingest_range(
                signals.per_person_min,
                signals.per_person_max,
                numbers,
                prefer_min=prefer_min,
                prefer_max=prefer_max,
            )
        else:
            signals.total_min, signals.total_max = _ingest_range(
                signals.total_min,
                signals.total_max,
                numbers,
                prefer_min=prefer_min,
                prefer_max=prefer_max,
            )

    return signals


def _build_flexible_dates(base_date: date, flex_days: int) -> List[str]:
    """Construit toutes les dates possibles autour d'une date approximative."""

    span = []
    for delta in range(-flex_days, flex_days + 1):
        span.append(_isoformat(base_date + timedelta(days=delta)))
    return span


def _shift_dates(dates: List[str], duration: int) -> List[str]:
    """Décale une liste de dates de `duration` jours."""

    results: List[str] = []
    for entry in dates:
        parsed = _parse_date(entry)
        if not parsed:
            continue
        results.append(_isoformat(parsed + timedelta(days=duration)))
    return results


def _parse_flex_days(value: Any) -> Optional[int]:
    if value is None:
        return None
    numbers = _extract_numbers(value)
    if not numbers:
        return None
    return int(numbers[0])


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        # Tente ISO direct
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            pass
        match = _DATE_PATTERN.search(value)
        if match:
            try:
                return datetime.fromisoformat(match.group(1)).date()
            except ValueError:
                return None
    return None


def _ensure_str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if value is None:
        return []
    return [str(value)]


def _split_city_country(value: str) -> Tuple[Optional[str], Optional[str]]:
    parts = [
        segment.strip()
        for segment in re.split(r"[,/|\-]", value)
        if segment.strip()
    ]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[-1]


def _extract_numbers(value: Any) -> List[float]:
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, str):
        cleaned = value.replace("\u00a0", " ")
        cleaned = re.sub(r"(?<=\d)[\s\u00a0](?=\d)", "", cleaned)
        cleaned = cleaned.replace("\u2212", "-").replace("\u00b1", " ")
        matches = _NUMBER_PATTERN.findall(cleaned)
        results: List[float] = []
        for match in matches:
            normalized = match.replace(",", ".")
            try:
                results.append(float(normalized))
            except ValueError:
                continue
        return results
    return []


def _isoformat(value: date) -> str:
    return value.isoformat()


def _to_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        numbers = _extract_numbers(value)
        if numbers:
            return int(numbers[0])
    return None


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        numbers = _extract_numbers(value)
        if numbers:
            return numbers[0]
    return None


def _normalize_amount(value: Optional[float]) -> Optional[float | int]:
    if value is None:
        return None
    rounded = round(value, 2)
    if abs(rounded - round(rounded)) < 1e-6:
        return int(round(rounded))
    return rounded


__all__ = ["enrich_trip_structural_data"]
