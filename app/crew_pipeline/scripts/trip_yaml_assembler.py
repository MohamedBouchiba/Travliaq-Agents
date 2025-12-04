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
    
    import uuid
    
    # Générer un suffixe unique de 6 caractères hex (garantit unicité)
    unique_suffix = uuid.uuid4().hex[:6].upper()
    
    if not raw_code:
        return f"TRIP-{unique_suffix}"
    
    code = str(raw_code).upper()
    code = re.sub(r"[^A-Z0-9]+", "-", code).strip("-")
    
    # Assurer que le code commence par une lettre
    if not code or not code[0].isalpha():
        code = f"T{code}" if code else "TRIP"
    
    # 🔧 FIX: Calculer la longueur max en tenant compte de TOUTE la structure finale
    # Format attendu: CODE-SUFFIX (ex: BANGKOK-A3F5E1)
    # Limite totale: 20 caractères max
    # Suffixe: 6 chars + 1 tiret = 7 chars réservés
    max_main_length = 20 - 7  # = 13 chars max pour la partie principale
    
    if len(code) > max_main_length:
        # Tronquer intelligemment: garder le début + fin si possible
        code = code[:max_main_length]
    
    # Ajouter le suffixe unique
    code_with_suffix = f"{code}-{unique_suffix}"
    
    # ✅ GARANTIE: Le code final fait TOUJOURS ≤ 20 caractères
    assert len(code_with_suffix) <= 20, f"Code trop long: {code_with_suffix} ({len(code_with_suffix)} chars)"
    
    # Vérifier la longueur minimale (au moins 3 caractères)
    if len(code_with_suffix) < 3:
        code_with_suffix = code_with_suffix.ljust(3, "X")
    
    return code_with_suffix


def _build_fallback_image(destination: Optional[str]) -> str:
    if destination:
        slug = quote(str(destination).lower().replace(" ", "-"))
        return f"https://source.unsplash.com/featured/?{slug},travel"
    return DEFAULT_MAIN_IMAGE


def _validate_bilingual_fields(step: Dict[str, Any], step_number: int) -> None:
    """Valide que les champs bilingues sont présents et complets."""

    bilingual_pairs = [
        ("title", "title_en"),
        ("subtitle", "subtitle_en"),
        ("why", "why_en"),
        ("tips", "tips_en"),
        ("transfer", "transfer_en"),
        ("suggestion", "suggestion_en"),
        ("weather_description", "weather_description_en"),
    ]

    missing_translations = []

    for fr_field, en_field in bilingual_pairs:
        # Si le champ FR existe et n'est pas vide, vérifier que la traduction EN existe
        if step.get(fr_field) and not step.get(en_field):
            missing_translations.append(f"{fr_field} → {en_field}")

    if missing_translations:
        logger.warning(
            f"⚠️ Step {step_number} manque des traductions EN: {', '.join(missing_translations)}"
        )

    # Vérifier les champs GPS pour les steps non-transport
    step_type = step.get("step_type", "").lower()
    is_transport = "transport" in step_type or "récap" in step_type.lower()
    is_summary = step.get("is_summary", False)

    if not is_transport and not is_summary:
        if not step.get("latitude") or not step.get("longitude"):
            logger.warning(
                f"⚠️ Step {step_number} manque des coordonnées GPS (latitude/longitude)"
            )

    # Vérifier l'URL de l'image
    main_image = step.get("main_image", "")
    if main_image:
        if "supabase.co" not in main_image and "http" in main_image:
            logger.warning(
                f"⚠️ Step {step_number} utilise une URL externe pour main_image: {main_image[:100]}"
            )


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
    """Crée une étape enrichie par défaut pour garantir une couverture quotidienne."""

    destination_label = trip_core.get("destination") or "Destination"
    destination_en = trip_core.get("destination_en") or destination_label

    style_hint_fr = ""
    style_hint_en = ""
    if styles:
        joined_fr = ", ".join(str(style) for style in styles[:3])
        if joined_fr:
            style_hint_fr = f" Mettez l'accent sur : {joined_fr}."
            # Traductions simplifiées des styles courants
            style_translations = {
                "Culture": "Culture",
                "Gastronomie": "Gastronomy",
                "Nature": "Nature",
                "Aventure": "Adventure",
                "Détente": "Relaxation",
                "Nightlife": "Nightlife"
            }
            joined_en = ", ".join(style_translations.get(style, style) for style in styles[:3])
            style_hint_en = f" Focus on: {joined_en}."

    main_image = trip_core.get("main_image") or _build_fallback_image(destination_label)

    # 🎯 PLACEHOLDER ENRICHI avec champs bilingues
    logger.warning(
        f"⚠️ Génération d'un placeholder pour le jour {day_number} - "
        f"L'agent itinerary_designer n'a pas fourni de step détaillée"
    )

    return {
        "step_number": day_number,
        "day_number": day_number,
        "title": f"Jour {day_number} – Découverte de {destination_label}",
        "title_en": f"Day {day_number} – Discovering {destination_en}",
        "subtitle": f"Exploration libre à {destination_label}",
        "subtitle_en": f"Free exploration in {destination_en}",
        "main_image": main_image,
        "step_type": "activité",
        "duration": "Journée complète",
        "price": 0,
        "why": f"Itinéraire libre pour explorer {destination_label} à votre rythme.{style_hint_fr}",
        "why_en": f"Free itinerary to explore {destination_en} at your own pace.{style_hint_en}",
        "tips": "Ajoutez ici vos activités ou restaurants préférés pour personnaliser cette journée.",
        "tips_en": "Add your favorite activities or restaurants here to customize this day.",
        "weather_icon": "🌤️",
        "weather_temp": trip_core.get("average_weather") or "22°C",
        "weather_description": "Agréable",
        "weather_description_en": "Pleasant",
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

    # 🔧 EXTRACTION ROBUSTE: Chercher les données dans plusieurs structures possibles
    # Les agents peuvent retourner leurs données sous différentes clés

    # VOLS: Chercher flight_quotes dans plusieurs endroits
    flight_quotes = []
    if isinstance(flights.get("flight_quotes"), list):
        flight_quotes = flights.get("flight_quotes")
    elif isinstance(flights.get("options"), list):
        flight_quotes = flights.get("options")
    elif isinstance(flights.get("quotes"), list):
        flight_quotes = flights.get("quotes")

    first_quote = flight_quotes[0] if flight_quotes and isinstance(flight_quotes[0], dict) else {}

    # Si pas de quotes individuels, chercher les données dans l'objet flights directement
    if not first_quote and flights:
        first_quote = {
            "from": flights.get("from") or flights.get("departure") or flights.get("flight_from"),
            "to": flights.get("to") or flights.get("arrival") or flights.get("flight_to"),
            "price": flights.get("price") or flights.get("total_price") or flights.get("price_display"),
            "duration": flights.get("duration") or flights.get("flight_duration"),
            "type": flights.get("type") or flights.get("flight_type"),
        }

    # HÉBERGEMENT: Chercher lodging_quotes dans plusieurs endroits
    lodging_quotes = []
    if isinstance(lodging.get("lodging_quotes"), list):
        lodging_quotes = lodging.get("lodging_quotes")
    elif isinstance(lodging.get("options"), list):
        lodging_quotes = lodging.get("options")
    elif isinstance(lodging.get("quotes"), list):
        lodging_quotes = lodging.get("quotes")

    first_lodging = lodging_quotes[0] if lodging_quotes and isinstance(lodging_quotes[0], dict) else {}

    # Si pas de quotes individuels, chercher dans l'objet lodging directement
    if not first_lodging and lodging:
        first_lodging = {
            "hotel_name": lodging.get("hotel_name") or lodging.get("name") or lodging.get("accommodation_name"),
            "hotel_rating": lodging.get("hotel_rating") or lodging.get("rating") or lodging.get("stars"),
            "total_price": lodging.get("total_price") or lodging.get("price") or lodging.get("price_display"),
            "price": lodging.get("price_per_night") or lodging.get("price"),
        }

    # 🔍 LOGGING DÉTAILLÉ pour debug
    logger.info(
        f"📊 Données extraites: "
        f"flights={bool(first_quote)} (keys: {list(first_quote.keys()) if first_quote else 'None'}), "
        f"lodging={bool(first_lodging)} (keys: {list(first_lodging.keys()) if first_lodging else 'None'}), "
        f"activities_steps={len(activities.get('steps', [])) if activities else 0}"
    )

    if first_quote:
        logger.info(f"   ✈️  Vol: {first_quote.get('from')} → {first_quote.get('to')}, prix={first_quote.get('price')}, durée={first_quote.get('duration')}, type={first_quote.get('type')}")

    if first_lodging:
        logger.info(f"   🏨 Hébergement: {first_lodging.get('hotel_name')}, note={first_lodging.get('hotel_rating')}, prix={first_lodging.get('total_price') or first_lodging.get('price')}")

    # 🛡️ ROBUST DESTINATION EXTRACTION
    # Extrait la destination depuis plusieurs sources possibles
    def _extract_destination() -> str:
        # Priorité 1: destination_choice (agent strategist)
        if destination_choice.get("destination"):
            return destination_choice["destination"]
        
        # Priorité 2: questionnaire direct
        for key in ("destination", "destination_precise", "lieu_arrivee"):
            if questionnaire.get(key):
                return questionnaire[key]
        
        # Priorité 3: normalized_trip_request nested
        trip_frame = normalized_trip_request.get("trip_frame", {})
        if isinstance(trip_frame, dict):
            destinations = trip_frame.get("destinations", [])
            if isinstance(destinations, list) and destinations:
                first_dest = destinations[0]
                if isinstance(first_dest, dict) and first_dest.get("city"):
                    return first_dest["city"]
        
        # Fallback sécurisé
        return "Destination à préciser"
    
    # 🛡️ CALCUL DU PRIX TOTAL COMPLET (vols + hébergement + activités + transport local)
    # Extraire les prix de chaque catégorie
    price_flights = _parse_price(first_quote.get("price") or flights.get("total_price") or flights.get("price") or 0)
    price_hotels = _parse_price(first_lodging.get("total_price") or first_lodging.get("price") or lodging.get("total_price") or lodging.get("price") or 0)

    # Prix activités : somme de tous les steps
    price_activities = 0
    raw_steps = activities.get("steps") if isinstance(activities.get("steps"), list) else []
    for step in raw_steps:
        if isinstance(step, dict) and not step.get("is_summary"):
            step_price = _parse_price(step.get("price"))
            if step_price:
                price_activities += step_price

    # Transport local : estimation si non fourni (10-15€/jour/personne)
    price_transport = _parse_price(destination_choice.get("price_transport"))
    if not price_transport:
        total_days = _coerce_positive_int(
            destination_choice.get("total_days")
            or normalized_trip_request.get("nuits_exactes")
            or questionnaire.get("nuits_exactes"),
            1,
        )
        travelers_count = _coerce_positive_int(questionnaire.get("nombre_voyageurs"), 1)
        price_transport = total_days * 15 * travelers_count  # 15€/jour/personne

    # PRIX GLOBAL COMPLET
    total_price_calculated = (price_flights or 0) + (price_hotels or 0) + (price_activities or 0) + (price_transport or 0)
    total_price_display = f"{int(total_price_calculated)}€" if total_price_calculated > 0 else None

    # 🛡️ TOUJOURS générer un code unique (même si l'agent en a fourni un)
    # Cela évite les conflits de clé primaire en base
    trip_code = _normalize_trip_code(
        destination_choice.get("destination") or questionnaire.get("destination") or "TRIP"
    )

    # 🛡️ EXTRACTION HERO IMAGE: Chercher dans TOUTES les sources possibles
    # L'agent génère hero_image dans itinerary_plan, parfois dans destination_choice
    hero_image_candidate = (
        activities.get("hero_image")  # ← PRIORITÉ 1: L'agent le met ici
        or activities.get("main_image")
        or activities.get("itinerary_plan", {}).get("hero_image")  # Parfois imbriqué
        or destination_choice.get("main_image")
        or destination_choice.get("hero_image")
    )

    # 🔍 EXTRACTION AVANCÉE: Si pas trouvé, chercher dans le raw_output YAML
    if not hero_image_candidate or "FAILED" in str(hero_image_candidate).upper():
        import re
        # Chercher pattern: hero_image: "https://...supabase.co/..."
        for source_data in [activities, destination_choice]:
            raw_output = source_data.get("raw_output", "")
            if isinstance(raw_output, str):
                match = re.search(r'hero_image:\s*["\']?(https://[^"\'\s]+supabase\.co[^"\'\s]+)["\']?', raw_output, re.IGNORECASE)
                if match:
                    hero_image_candidate = match.group(1)
                    logger.info(f"✅ Hero image extraite depuis raw_output: {hero_image_candidate}")
                    break

    logger.info(f"🖼️ Hero image candidate: {hero_image_candidate or 'None'}")

    trip_core = {
        "code": trip_code,  # 🎯 Code UNIQUE avec UUID
        "destination": _extract_destination(),
        "destination_en": destination_choice.get("destination_en"),
        "total_days": _coerce_positive_int(
            destination_choice.get("total_days")
            or normalized_trip_request.get("nuits_exactes")
            or questionnaire.get("nuits_exactes"),
            1,
        ),
        "main_image": hero_image_candidate,
        "flight_from": first_quote.get("from") or flights.get("from") or questionnaire.get("lieu_depart"),
        "flight_to": first_quote.get("to") or flights.get("to") or questionnaire.get("destination"),
        "flight_duration": first_quote.get("duration") or flights.get("duration"),
        "flight_type": first_quote.get("type") or flights.get("type"),
        "hotel_name": first_lodging.get("hotel_name") or lodging.get("hotel_name"),
        "hotel_rating": first_lodging.get("hotel_rating") or lodging.get("hotel_rating"),
        "total_price": total_price_display,  # 🎯 PRIX COMPLET CALCULÉ
        "total_budget": total_price_display,  # 🎯 MÊME VALEUR QUE total_price
        "average_weather": destination_choice.get("average_weather"),
        "travel_style": destination_choice.get("travel_style"),
        "travel_style_en": destination_choice.get("travel_style_en"),
        "start_date": _normalize_start_date(questionnaire.get("date_depart")),
        "travelers": questionnaire.get("nombre_voyageurs"),
        "price_flights": f"{int(price_flights)}€" if price_flights else None,
        "price_hotels": f"{int(price_hotels)}€" if price_hotels else None,
        "price_transport": f"{int(price_transport)}€" if price_transport else None,
        "price_activities": f"{int(price_activities)}€" if price_activities else None,
    }

    # 🖼️ VALIDATION IMAGE HERO: Priorité aux URLs MCP Supabase (workflow correct)
    hero_image = trip_core.get("main_image")
    # ✅ WORKFLOW CORRECT: Garder les URLs Supabase générées par images.hero
    if hero_image and "supabase.co" in str(hero_image):
        logger.info(f"✅ Hero image Supabase MCP trouvée: {hero_image}")
    elif not hero_image:
        # Fallback SEULEMENT si complètement vide (pas d'appel MCP réussi)
        trip_core["main_image"] = _build_fallback_image(trip_core.get("destination"))
        logger.warning("⚠️ Aucune hero image générée, utilisation du fallback Unsplash")
    # ⚠️ NE PLUS remplacer les "FAILED" - l'agent doit utiliser les outils MCP correctement

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

        # 🖼️ VALIDATION IMAGE STEP: Priorité aux URLs MCP Supabase (workflow correct)
        # ✅ WORKFLOW CORRECT: L'agent doit appeler images.background() pour CHAQUE step
        if main_image and "supabase.co" in str(main_image):
            logger.debug(f"✅ Step {step_number}: Image Supabase MCP trouvée")
        elif not main_image:
            # Fallback SEULEMENT si complètement vide
            main_image = _build_fallback_image(trip_core.get("destination"))
            logger.warning(f"⚠️ Step {step_number}: Aucune image générée, fallback Unsplash")
        # ⚠️ NE PLUS remplacer les "FAILED" - forcer l'agent à utiliser les outils MCP

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

        # 🛡️ VALIDATION: Vérifier les champs bilingues et GPS
        _validate_bilingual_fields(sanitized_step, step_number)

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
