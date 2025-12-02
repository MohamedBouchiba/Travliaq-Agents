"""Assemblage final du YAML `trip` à partir des artefacts d'agents et de scripts."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

DEFAULT_MAIN_IMAGE = "https://images.unsplash.com/photo-1507525428034-b723cf961d3e"

SUMMARY_SIMPLE_TYPES = {"days", "budget", "weather", "style", "cities", "people", "activities"}
STEP_ALLOWED_KEYS = {
    "step_number",
    "day_number",
    "title",
    "title_en",
    "subtitle",
    "subtitle_en",
    "main_image",
    "is_summary",
    "step_type",
    "latitude",
    "longitude",
    "why",
    "why_en",
    "tips",
    "tips_en",
    "transfer",
    "transfer_en",
    "suggestion",
    "suggestion_en",
    "weather_icon",
    "weather_temp",
    "weather_description",
    "weather_description_en",
    "price",
    "duration",
    "images",
    "summary_stats",
}


def _safe_get(output_map: Dict[str, Any], key: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    value = output_map.get(key)
    return value if isinstance(value, dict) else (default or {})


def _coerce_positive_int(value: Any, fallback: int) -> int:
    """Retourne un entier positif ou un fallback."""

    try:
        int_value = int(value)
        if int_value > 0:
            return int_value
    except (TypeError, ValueError):
        pass
    return fallback


def _extract_summary_stats(final_choice: Dict[str, Any]) -> List[Dict[str, Any]]:
    stats = final_choice.get("summary_stats")
    if isinstance(stats, list):
        return stats
    return []


def _normalize_trip_code(raw_code: Optional[str]) -> str:
    """Normalise le code du trip pour respecter la règle `^[A-Z][A-Z0-9-]{2,19}$`."""

    if not raw_code:
        return "TRIP"

    code = str(raw_code).upper()
    code = re.sub(r"[^A-Z0-9]+", "-", code).strip("-")

    # Assurer que le code commence par une lettre et fait au moins 3 caractères
    if not code or not code[0].isalpha():
        code = f"T{code}" if code else "TRIP"

    code = code[:20]
    if len(code) < 3:
        code = code.ljust(3, "X")

    return code


def _build_fallback_image(destination: Optional[str]) -> str:
    if destination:
        slug = quote(str(destination).lower().replace(" ", "-"))
        return f"https://source.unsplash.com/featured/?{slug},travel"
    return DEFAULT_MAIN_IMAGE


def _parse_price(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"[0-9]+(?:[\.,][0-9]+)?", value)
        if match:
            try:
                return float(match.group(0).replace(",", "."))
            except ValueError:
                return None
    return None


def _normalize_start_date(value: Any) -> Any:
    if isinstance(value, str) and "T" in value:
        return value.split("T", 1)[0]
    return value


def _sanitize_summary_stat(stat: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Nettoie une statistique pour respecter le schéma."""

    if not isinstance(stat, dict):
        return None

    stat_type = stat.get("type")
    if stat_type in SUMMARY_SIMPLE_TYPES and "value" in stat:
        return {"type": stat_type, "value": stat.get("value")}

    if stat_type == "custom":
        color = stat.get("color")
        if color not in {"turquoise", "golden"}:
            color = "turquoise"
        if all(field in stat for field in ("value", "icon", "label")):
            return {
                "type": "custom",
                "value": stat.get("value"),
                "icon": stat.get("icon") or "Map",
                "label": stat.get("label") or "INFO",
                "color": color,
            }
    return None


def _build_placeholder_step(
    day_number: int, trip_core: Dict[str, Any], styles: Optional[List[str]]
) -> Dict[str, Any]:
    """Crée une étape par défaut pour garantir une couverture quotidienne."""

    destination_label = trip_core.get("destination") or "Destination"
    style_hint = ""
    if styles:
        joined = ", ".join(str(style) for style in styles[:3])
        if joined:
            style_hint = f" Mettez l'accent sur : {joined}."

    main_image = trip_core.get("main_image") or _build_fallback_image(destination_label)

    return {
        "step_number": day_number,
        "day_number": day_number,
        "title": f"Jour {day_number} – Découverte de {destination_label}",
        "main_image": main_image,
        "step_type": "activité",
        "duration": "Journée",
        "price": 0,
        "why": f"Itinéraire libre pour explorer {destination_label} à votre rythme." + style_hint,
        "tips": "Ajoutez ici vos activités ou restaurants préférés pour personnaliser cette journée.",
        "images": [main_image],
    }


def _ensure_daily_coverage(
    steps: List[Dict[str, Any]],
    trip_core: Dict[str, Any],
    target_total_days: int,
    styles: Optional[List[str]],
) -> List[Dict[str, Any]]:
    """Garantit entre 1 et 3 étapes par jour en ajoutant des placeholders si nécessaire."""

    non_summary_steps = [step for step in steps if not step.get("is_summary")]
    steps_by_day: Dict[int, List[Dict[str, Any]]] = {}

    for step in non_summary_steps:
        day = _coerce_positive_int(step.get("day_number"), step.get("step_number") or 1)
        steps_by_day.setdefault(day, []).append(step)

    for day in range(1, target_total_days + 1):
        daily_steps = steps_by_day.get(day, [])
        if not daily_steps:
            placeholder = _build_placeholder_step(day, trip_core, styles)
            steps.append(placeholder)
            steps_by_day.setdefault(day, []).append(placeholder)
        elif len(daily_steps) > 3:
            steps_by_day[day] = daily_steps[:3]

    pruned: List[Dict[str, Any]] = []
    for day in range(1, target_total_days + 1):
        daily_steps = steps_by_day.get(day, [])
        if len(daily_steps) > 3:
            daily_steps = daily_steps[:3]
        pruned.extend(daily_steps)

    orphan_steps = [
        step
        for step in steps
        if not step.get("is_summary")
        and _coerce_positive_int(step.get("day_number"), 0) > target_total_days
    ]
    pruned.extend(orphan_steps)

    return sorted(
        pruned, key=lambda s: (_coerce_positive_int(s.get("day_number"), 1), s.get("step_number", 0))
    )


def _build_summary_stats(trip_core: Dict[str, Any], steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Construit un jeu de statistiques (4-8 items) à partir des données disponibles."""

    stats: List[Dict[str, Any]] = []

    def _add_simple(stat_type: str, value: Any) -> None:
        if value is not None:
            stats.append({"type": stat_type, "value": value})

    _add_simple("days", trip_core.get("total_days"))
    _add_simple("budget", trip_core.get("total_budget") or trip_core.get("total_price"))
    _add_simple("weather", trip_core.get("average_weather"))
    _add_simple("style", trip_core.get("travel_style"))
    _add_simple("people", trip_core.get("travelers"))

    activities_count = sum(1 for step in steps if not step.get("is_summary"))
    if activities_count:
        _add_simple("activities", activities_count)

    if len(stats) < 4:
        _add_simple("cities", 1)

    while len(stats) < 4:
        stats.append(
            {
                "type": "custom",
                "value": "Info",
                "icon": "Map",
                "label": "TRIP",
                "color": "turquoise",
            }
        )

    if len(stats) > 8:
        stats = stats[:8]

    return stats


def _sanitize_summary_stats_or_build(
    sanitized_stats: List[Dict[str, Any]],
    trip_core: Dict[str, Any],
    steps: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Retourne une liste de stats valide (4-8) ou construit un fallback."""

    cleaned = [stat for stat in sanitized_stats if stat]
    if len(cleaned) < 4:
        cleaned.extend(_build_summary_stats(trip_core, steps))

    if len(cleaned) > 8:
        cleaned = cleaned[:8]

    if len(cleaned) < 4:
        cleaned = _build_summary_stats(trip_core, steps)

    return cleaned


def assemble_trip(
    *,
    questionnaire: Dict[str, Any],
    normalized_trip_request: Dict[str, Any],
    agent_outputs: Dict[str, Any],
) -> Dict[str, Any]:
    """Consolide le voyage final en respectant le schéma Trip."""

    destination_choice = _safe_get(agent_outputs, "destination_decision")
    flights = _safe_get(agent_outputs, "flight_pricing")
    lodging = _safe_get(agent_outputs, "lodging_pricing")
    activities = _safe_get(agent_outputs, "activities_geo_design")

    flight_quotes = flights.get("flight_quotes") if isinstance(flights.get("flight_quotes"), list) else []
    first_quote = flight_quotes[0] if flight_quotes and isinstance(flight_quotes[0], dict) else {}

    lodging_quotes = lodging.get("lodging_quotes") if isinstance(lodging.get("lodging_quotes"), list) else []
    first_lodging = lodging_quotes[0] if lodging_quotes and isinstance(lodging_quotes[0], dict) else {}

    trip_core = {
        "code": _normalize_trip_code(
            destination_choice.get("code") or questionnaire.get("destination") or "TRIP"
        ),
        "destination": destination_choice.get("destination") or questionnaire.get("destination") or "Destination",
        "destination_en": destination_choice.get("destination_en"),
        "total_days": _coerce_positive_int(
            destination_choice.get("total_days")
            or normalized_trip_request.get("nuits_exactes")
            or questionnaire.get("nuits_exactes"),
            1,
        ),
        "main_image": destination_choice.get("main_image"),
        "flight_from": first_quote.get("from") or flights.get("from") or questionnaire.get("lieu_depart"),
        "flight_to": first_quote.get("to") or flights.get("to") or questionnaire.get("destination"),
        "flight_duration": first_quote.get("duration") or flights.get("duration"),
        "flight_type": first_quote.get("type") or flights.get("type"),
        "hotel_name": first_lodging.get("hotel_name") or lodging.get("hotel_name"),
        "hotel_rating": first_lodging.get("hotel_rating") or lodging.get("hotel_rating"),
        "total_price": destination_choice.get("total_price") or destination_choice.get("total_budget"),
        "total_budget": destination_choice.get("total_budget") or questionnaire.get("budget_par_personne"),
        "average_weather": destination_choice.get("average_weather"),
        "travel_style": destination_choice.get("travel_style"),
        "travel_style_en": destination_choice.get("travel_style_en"),
        "start_date": _normalize_start_date(questionnaire.get("date_depart")),
        "travelers": questionnaire.get("nombre_voyageurs"),
        "price_flights": first_quote.get("price") or flights.get("price"),
        "price_hotels": first_lodging.get("price") or lodging.get("price"),
        "price_transport": destination_choice.get("price_transport"),
        "price_activities": activities.get("price"),
    }

    if not trip_core.get("main_image"):
        trip_core["main_image"] = _build_fallback_image(trip_core.get("destination"))

    raw_steps = activities.get("steps") if isinstance(activities.get("steps"), list) else []
    sanitized_steps: List[Dict[str, Any]] = []
    trip_styles = normalized_trip_request.get("styles") if isinstance(normalized_trip_request.get("styles"), list) else []
    target_total_days = _coerce_positive_int(
        trip_core.get("total_days")
        or normalized_trip_request.get("nuits_exactes")
        or questionnaire.get("nuits_exactes"),
        1,
    )

    for idx, step in enumerate(raw_steps, start=1):
        if not isinstance(step, dict):
            continue

        filtered_step = {k: step.get(k) for k in STEP_ALLOWED_KEYS if k in step}

        step_number = _coerce_positive_int(filtered_step.get("step_number"), idx)
        day_number = _coerce_positive_int(filtered_step.get("day_number"), step_number)
        title = filtered_step.get("title") or f"Étape {step_number}"
        main_image = filtered_step.get("main_image") or trip_core.get("main_image")
        if not main_image:
            main_image = _build_fallback_image(trip_core.get("destination"))

        sanitized_step: Dict[str, Any] = {
            "step_number": step_number,
            "day_number": day_number,
            "title": title,
            "main_image": main_image,
            "is_summary": bool(filtered_step.get("is_summary")),
        }

        # Champs optionnels
        for key in (
            "title_en",
            "subtitle",
            "subtitle_en",
            "step_type",
            "latitude",
            "longitude",
            "why",
            "why_en",
            "tips",
            "tips_en",
            "transfer",
            "transfer_en",
            "suggestion",
            "suggestion_en",
            "weather_icon",
            "weather_temp",
            "weather_description",
            "weather_description_en",
            "duration",
        ):
            if key in filtered_step:
                sanitized_step[key] = filtered_step.get(key)

        if "price" in filtered_step:
            sanitized_step["price"] = _parse_price(filtered_step.get("price"))

        images = filtered_step.get("images") if isinstance(filtered_step.get("images"), list) else []
        if main_image and main_image not in images:
            images.insert(0, main_image)
        if images:
            sanitized_step["images"] = images

        # Nettoyage/validité du summary
        raw_stats = filtered_step.get("summary_stats") if sanitized_step.get("is_summary") else []
        if sanitized_step.get("is_summary"):
            sanitized_stats = [s for s in (_sanitize_summary_stat(s) for s in (raw_stats or [])) if s]
            sanitized_step["summary_stats"] = _sanitize_summary_stats_or_build(
                sanitized_stats, trip_core, sanitized_steps
            )

        sanitized_steps.append(sanitized_step)

    sanitized_steps = _ensure_daily_coverage(
        sanitized_steps, trip_core, target_total_days, trip_styles
    )

    # Ajout d'un résumé si absent
    has_summary = any(step.get("is_summary") for step in sanitized_steps)
    if not has_summary:
        summary_step_number = len(sanitized_steps) + 1
        existing_summary_stats = [
            stat
            for stat in (
                _sanitize_summary_stat(stat) for stat in _extract_summary_stats(destination_choice)
            )
            if stat
        ]
        summary_step = {
            "step_number": summary_step_number,
            "day_number": trip_core.get("total_days") or summary_step_number,
            "title": "Résumé du voyage",
            "main_image": trip_core.get("main_image") or _build_fallback_image(trip_core.get("destination")),
            "is_summary": True,
            "step_type": "récapitulatif",
        }
        summary_step["summary_stats"] = _sanitize_summary_stats_or_build(
            existing_summary_stats, trip_core, sanitized_steps
        )
        summary_step["images"] = [summary_step["main_image"]]
        sanitized_steps.append(summary_step)

    # Harmoniser step_number après insertion éventuelle du résumé
    for idx, step in enumerate(sanitized_steps, start=1):
        step["step_number"] = idx
        if not step.get("day_number"):
            step["day_number"] = idx

    max_day_number = max((step.get("day_number", 0) for step in sanitized_steps), default=1)
    trip_core["total_days"] = _coerce_positive_int(
        trip_core.get("total_days"), max_day_number
    )

    non_summary_steps = [step for step in sanitized_steps if not step.get("is_summary")]
    for step in sanitized_steps:
        if step.get("is_summary"):
            sanitized_stats = [
                stat
                for stat in (
                    _sanitize_summary_stat(stat) for stat in step.get("summary_stats", [])
                )
                if stat
            ]
            step["summary_stats"] = _sanitize_summary_stats_or_build(
                sanitized_stats, trip_core, non_summary_steps
            )

    trip = {
        "trip": {
            **trip_core,
            "steps": sanitized_steps,
        }
    }

    return trip
