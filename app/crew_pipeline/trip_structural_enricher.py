"""Post-traitements déterministes sur le JSON normalisé du voyage."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

_NUMBER_PATTERN = re.compile(r"-?\d+(?:[.,]\d+)?")
_DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _flatten_questionnaire_data(source: Mapping[str, Any]) -> Dict[str, Any]:
    """Aplati le questionnaire pour exposer toutes les clés utiles."""

    flattened: Dict[str, Any] = {}
    base = dict(source)
    flattened.update(base)

    stack: List[Tuple[List[str], Mapping[str, Any]]] = [([], source)]
    while stack:
        path, current = stack.pop()
        for key, value in current.items():
            if not isinstance(key, str):
                continue
            next_path = path + [key]
            dotted = ".".join(next_path)
            if isinstance(value, Mapping):
                flattened.setdefault(key, value)
                flattened.setdefault(dotted, value)
                stack.append((next_path, value))
            else:
                if dotted:
                    flattened.setdefault(dotted, value)
                flattened.setdefault(key, value)

    return flattened


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

    if isinstance(questionnaire_data, Mapping):
        safe_questionnaire = _flatten_questionnaire_data(questionnaire_data)
    else:  # pragma: no cover - garde-fou supplémentaire
        safe_questionnaire = {}

    enriched = deepcopy(normalized_trip_request)

    travel_party = enriched.setdefault("travel_party", {})
    travellers_count = _ensure_travel_party_size(travel_party, safe_questionnaire)
    _ensure_travel_group_type(travel_party, safe_questionnaire)

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
        "number_of_travelers",
        "travel_party.travelers_count",
        "questionnaire.number_of_travelers",
        "questionnaire.travelers_count",
        "travelers.total",
    ]
    for key in candidates:
        value = questionnaire.get(key)
        parsed = _to_int(value)
        if parsed is not None and parsed > 0:
            travel_party["travelers_count"] = parsed
            return parsed

    return current


def _ensure_travel_group_type(
    travel_party: Dict[str, Any], questionnaire: Mapping[str, Any]
) -> None:
    """Assure que le type de groupe reflète le code interne du questionnaire."""

    existing = str(travel_party.get("group_type") or "").strip()
    if existing:
        travel_party["group_type"] = _normalize_group_type(existing) or existing
        return

    candidates = [
        "travel_group",
        "group_type",
        "profil_voyage",
        "groupe_voyage",
        "questionnaire.travel_group",
        "travel_party.group_type",
    ]
    for key in candidates:
        raw = questionnaire.get(key)
        normalized = _normalize_group_type(raw)
        if normalized:
            travel_party["group_type"] = normalized
            return


def _ensure_origin(enriched: Dict[str, Any], questionnaire: Mapping[str, Any]) -> None:
    """Renseigne systématiquement la ville/pays d'origine."""

    trip_frame = enriched.setdefault("trip_frame", {})
    origin = trip_frame.setdefault("origin", {})

    city = origin.get("city")
    country = origin.get("country")

    combined_candidates = [
        questionnaire.get("lieu_depart"),
        questionnaire.get("departure_location"),
        questionnaire.get("depart"),
        questionnaire.get("questionnaire.departure_location"),
    ]
    for combined in combined_candidates:
        if not combined or (city and country):
            continue
        extracted_city, extracted_country = _extract_city_country(combined)
        if extracted_city and not city:
            city = extracted_city
        if extracted_country and not country:
            country = extracted_country

    city_candidates = [
        "origin_city",
        "origin.city",
        "questionnaire.origin_city",
        "questionnaire.origin.city",
        "ville_depart",
        "depart_city",
        "depart_ville",
        "departure_city",
        "departure.city",
        "departure_location.city",
        "questionnaire.departure_location.city",
        "travel.origin.city",
    ]
    country_candidates = [
        "origin_country",
        "origin.country",
        "questionnaire.origin_country",
        "questionnaire.origin.country",
        "pays_depart",
        "depart_country",
        "depart_pays",
        "departure_country",
        "departure.country",
        "departure_location.country",
        "questionnaire.departure_location.country",
        "travel.origin.country",
    ]

    for key in city_candidates:
        if city:
            break
        candidate = questionnaire.get(key)
        if candidate:
            city = str(candidate).strip()

    for key in country_candidates:
        if country:
            break
        candidate = questionnaire.get(key)
        if candidate:
            country = str(candidate).strip()

    origin["city"] = city or None
    origin["country"] = country or None


def _ensure_dates(enriched: Dict[str, Any], questionnaire: Mapping[str, Any]) -> None:
    """Normalise les dates de départ/retour et les ranges flexibles."""

    trip_frame = enriched.setdefault("trip_frame", {})
    dates = trip_frame.setdefault("dates", {})

    duration = _extract_duration(dates, questionnaire)

    type_hint = str(dates.get("type") or "").lower()
    questionnaire_type = str(
        _first_value(
            questionnaire,
            "type_dates",
            "dates_type",
            "questionnaire.dates_type",
            "travel_dates.type",
        )
        or ""
    ).lower()
    approx_flag = str(
        _first_value(
            questionnaire,
            "a_date_depart_approximative",
            "has_flexible_dates",
            "questionnaire.has_flexible_dates",
        )
        or ""
    ).lower()
    flex_days = _parse_flex_days(
        _first_value(
            questionnaire,
            "flexibilite",
            "flexibility",
            "flexibility_days",
            "flex_days",
            "questionnaire.flexibility_days",
        )
    )
    flex_minus = _parse_flex_days(
        _first_value(
            questionnaire,
            "flexibilite_minus",
            "flexibility_minus",
            "flexibility_days_minus",
            "flex_days_minus",
        )
    )
    flex_plus = _parse_flex_days(
        _first_value(
            questionnaire,
            "flexibilite_plus",
            "flexibility_plus",
            "flexibility_days_plus",
            "flex_days_plus",
        )
    )
    approx_date = _parse_date(
        _first_value(
            questionnaire,
            "date_depart_approximative",
            "approx_departure_date",
            "dates.approx_departure",
            "questionnaire.dates.approx",
        )
    )

    range_start, range_end = _extract_range_from_questionnaire(
        questionnaire,
        start_keys=[
            "departure_window.start",
            "departure_range.start",
            "date_depart_min",
            "dates.range.start",
            "questionnaire.departure_window.start",
        ],
        end_keys=[
            "departure_window.end",
            "departure_range.end",
            "date_depart_max",
            "dates.range.end",
            "questionnaire.departure_window.end",
        ],
        text_keys=["departure_window", "departure_range", "dates.range"],
    )

    return_start, return_end = _extract_range_from_questionnaire(
        questionnaire,
        start_keys=[
            "return_window.start",
            "return_range.start",
            "date_retour_min",
            "questionnaire.return_window.start",
        ],
        end_keys=[
            "return_window.end",
            "return_range.end",
            "date_retour_max",
            "questionnaire.return_window.end",
        ],
        text_keys=["return_window", "return_range"],
    )

    is_flexible = any(
        value in {"flexible", "flex", "yes", "true", "1"}
        for value in (type_hint, questionnaire_type, approx_flag)
    )
    if flex_days is not None and flex_days > 0:
        is_flexible = True
    if range_start and range_end:
        is_flexible = True

    departure_dates: List[str] = []
    return_dates: List[str] = []

    if range_start and range_end:
        departure_dates = _build_date_range(range_start, range_end)
        dates["type"] = "flexible"
        dates["range"] = {
            "start": _isoformat(range_start),
            "end": _isoformat(range_end),
        }
    elif is_flexible and approx_date and (flex_days or flex_minus or flex_plus):
        minus = flex_minus if flex_minus is not None else flex_days or 0
        plus = flex_plus if flex_plus is not None else flex_days or 0
        span = _build_asymmetric_flex_dates(approx_date, minus, plus)
        departure_dates = span
        dates["type"] = "flexible"
        if span:
            dates["range"] = {"start": span[0], "end": span[-1]}
    else:
        departure = _parse_date(
            _first_value(
                questionnaire,
                "date_depart",
                "departure_date",
                "dates.departure",
                "travel_dates.departure",
                "questionnaire.departure_date",
            )
        )
        if departure:
            departure_dates = [_isoformat(departure)]
        else:
            candidate_lists = [
                questionnaire.get("departure_options"),
                questionnaire.get("possible_departure_dates"),
                questionnaire.get("candidate_departure_dates"),
            ]
            for candidate in candidate_lists:
                departure_dates = _ensure_str_list(candidate)
                if departure_dates:
                    break
            if not departure_dates:
                departure_dates = _ensure_str_list(dates.get("departure_dates"))

        retour = _parse_date(
            _first_value(
                questionnaire,
                "date_retour",
                "return_date",
                "dates.return",
                "travel_dates.return",
                "questionnaire.return_date",
            )
        )
        if retour:
            return_dates = [_isoformat(retour)]
        elif departure and duration:
            return_dates = [_isoformat(departure + timedelta(days=duration))]
        else:
            candidate_lists = [
                questionnaire.get("return_options"),
                questionnaire.get("possible_return_dates"),
                questionnaire.get("candidate_return_dates"),
            ]
            for candidate in candidate_lists:
                return_dates = _ensure_str_list(candidate)
                if return_dates:
                    break
            if not return_dates:
                return_dates = _ensure_str_list(dates.get("return_dates"))

        if not dates.get("type"):
            dates["type"] = "fixed"
        if duration and not dates.get("duration_nights"):
            dates["duration_nights"] = duration
        dates.pop("range", None)

    if duration:
        dates["duration_nights"] = duration

    if not return_dates and duration and departure_dates:
        return_dates = _shift_dates(departure_dates, duration)

    if not return_dates and return_start and return_end:
        return_dates = _build_date_range(return_start, return_end)
        dates["return_range"] = {
            "start": _isoformat(return_start),
            "end": _isoformat(return_end),
        }
    elif return_start and return_end:
        dates["return_range"] = {
            "start": _isoformat(return_start),
            "end": _isoformat(return_end),
        }

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
        questionnaire.get("budget_currency"),
        questionnaire.get("budget.currency"),
        questionnaire.get("questionnaire.budget.currency"),
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


def _build_asymmetric_flex_dates(
    base_date: date, minus_days: int, plus_days: int
) -> List[str]:
    span = []
    for delta in range(-abs(minus_days), abs(plus_days) + 1):
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
    return abs(int(numbers[0]))


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




def _first_value(questionnaire: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key is None:
            continue
        value = questionnaire.get(key)
        if value not in (None, "", []):
            return value
    return None


def _extract_city_country(value: Any) -> Tuple[Optional[str], Optional[str]]:
    if isinstance(value, Mapping):
        city = value.get("city") or value.get("ville")
        country = value.get("country") or value.get("pays")
        return _normalize_text(city), _normalize_text(country)
    if isinstance(value, str):
        return _split_city_country(value)
    return None, None


def _normalize_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_group_type(value: Any) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None

    canonical = {
        "solo": {"solo", "seul"},
        "duo": {"duo", "couple"},
        "group35": {"groupe 3-5", "group35", "group 3-5", "groupe", "groupe35"},
        "family": {"famille", "family"},
    }
    for code, variants in canonical.items():
        if normalized in variants:
            return code
    return normalized


def _extract_range_from_questionnaire(
    questionnaire: Mapping[str, Any],
    *,
    start_keys: List[str],
    end_keys: List[str],
    text_keys: List[str],
) -> Tuple[Optional[date], Optional[date]]:
    start = _parse_date(_first_value(questionnaire, *start_keys))
    end = _parse_date(_first_value(questionnaire, *end_keys))

    window_candidates = [questionnaire.get(key) for key in text_keys]
    for candidate in window_candidates:
        if isinstance(candidate, Mapping):
            if not start:
                start = _parse_date(candidate.get("start"))
            if not end:
                end = _parse_date(candidate.get("end"))
        elif isinstance(candidate, str):
            parsed_start, parsed_end = _parse_range_from_text(candidate)
            if parsed_start and not start:
                start = parsed_start
            if parsed_end and not end:
                end = parsed_end

    if start and end and end < start:
        start, end = end, start

    return start, end


def _parse_range_from_text(value: str) -> Tuple[Optional[date], Optional[date]]:
    matches = _DATE_PATTERN.findall(value or "")
    if len(matches) >= 2:
        first = _parse_date(matches[0])
        second = _parse_date(matches[1])
        return first, second
    return None, None


def _build_date_range(start: date, end: date) -> List[str]:
    if not start or not end:
        return []
    if end < start:
        start, end = end, start
    span: List[str] = []
    current = start
    while current <= end:
        span.append(_isoformat(current))
        current += timedelta(days=1)
    return span

__all__ = ["enrich_trip_structural_data"]
