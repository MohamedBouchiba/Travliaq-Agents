"""
Incremental Trip JSON Builder

Construit le trip JSON progressivement pendant l'exécution de la pipeline,
au lieu d'attendre la fin pour tout assembler.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


class IncrementalTripBuilder:
    """
    Builder qui construit le trip JSON progressivement pendant l'exécution de la pipeline.

    Flow:
    1. Après PHASE1 (destination connue) → initialize_structure()
    2. Pendant PHASE2 → Chaque agent enrichit via setters
    3. Après PHASE3 → get_json() pour sauvegarder

    Avantages:
    - Structure créée dès le début avec N steps vides
    - Chaque agent remplit ses champs progressivement
    - Images générées en temps réel (MCP fallback automatique)
    - GPS calculés automatiquement si manquants
    - Validation progressive de la complétude
    """

    def __init__(self, questionnaire: Dict[str, Any]):
        """
        Initialiser avec le questionnaire.

        Args:
            questionnaire: Questionnaire normalisé de l'utilisateur
        """
        self.questionnaire = questionnaire
        self.trip_json = None  # Sera créé dans initialize_structure()
        self.mcp_tools = []  # Pour appels directs si besoin

        logger.info("🏗️ IncrementalTripBuilder créé")

    # =========================================================================
    # INITIALIZATION (après PHASE1 - dès qu'on a destination + dates)
    # =========================================================================

    def initialize_structure(
        self,
        destination: str,
        destination_en: str,
        start_date: str,
        rhythm: str,
        mcp_tools: List[Any],
    ) -> None:
        """
        Crée la structure JSON vide avec le bon nombre de steps.

        Calcul du nombre de steps:
        - Nombre de jours = durée questionnaire
        - Nombre de steps = jours × multiplicateur selon rythme:
          * relaxed: 1-2 steps/jour → multiplicateur 1.5
          * balanced: 1-2 steps/jour → multiplicateur 1.5
          * intense: 2-3 steps/jour → multiplicateur 2.5

        Args:
            destination: Destination principale (ex: "Bali, Indonésie")
            destination_en: Destination en anglais
            start_date: Date de départ (YYYY-MM-DD)
            rhythm: Rythme du voyageur ("relaxed", "balanced", "intense")
            mcp_tools: Liste des outils MCP pour appels directs
        """
        self.mcp_tools = mcp_tools

        # Calculer nombre de jours
        total_days = self._calculate_total_days(start_date)

        # Calculer nombre de steps selon rythme
        num_steps = self._calculate_steps_count(total_days, rhythm)

        # Générer code unique
        code = self._generate_code(destination)

        # 🔧 FIX: Créer structure correcte (steps DANS trip, pas à côté)
        self.trip_json = {
            "code": code,
            "destination": destination,
            "destination_en": destination_en,
            "total_days": total_days,
            "main_image": "",
            "flight_from": "",
            "flight_to": "",
            "flight_duration": "",
            "flight_type": "",
            "hotel_name": "",
            "hotel_rating": 0,
            "total_price": "",
            "total_budget": "",
            "average_weather": "",
            "travel_style": "",
            "travel_style_en": "",
            "start_date": start_date,
            "travelers": self.questionnaire.get("nombre_voyageurs", 2),
            "price_flights": "",
            "price_hotels": "",
            "price_transport": "",
            "price_activities": "",
            "steps": []  # 🔧 FIX: Steps DANS le trip
        }

        # Créer steps vides (activités)
        for i in range(1, num_steps + 1):
            day_number = self._calculate_day_number(i, num_steps, total_days)
            self.trip_json["steps"].append({
                "step_number": i,
                "day_number": day_number,
                "title": "",
                "title_en": "",
                "subtitle": "",
                "subtitle_en": "",
                "main_image": "",
                "step_type": "",
                "is_summary": False,
                "latitude": 0,
                "longitude": 0,
                "why": "",
                "why_en": "",
                "tips": "",
                "tips_en": "",
                "transfer": "",
                "transfer_en": "",
                "suggestion": "",
                "suggestion_en": "",
                "weather_icon": None,
                "weather_temp": "",
                "weather_description": "",
                "weather_description_en": "",
                "price": 0,
                "duration": "",
                "images": []
            })

        # Ajouter step summary (toujours la dernière)
        self.trip_json["steps"].append({
            "step_number": 99,
            "day_number": 0,
            "title": "Résumé du voyage",
            "title_en": "Trip Summary",
            "subtitle": "Votre voyage en un coup d'œil",
            "subtitle_en": "Your trip at a glance",
            "main_image": "",
            "step_type": "summary",
            "is_summary": True,
            "latitude": 0,
            "longitude": 0,
            "why": "",
            "why_en": "",
            "tips": "",
            "tips_en": "",
            "transfer": "",
            "transfer_en": "",
            "suggestion": "",
            "suggestion_en": "",
            "weather_icon": None,
            "weather_temp": "",
            "weather_description": "",
            "weather_description_en": "",
            "price": 0,
            "duration": "",
            "images": [],
            "summary_stats": [
                {"type": "days", "value": str(total_days)},
                {"type": "budget", "value": ""},
                {"type": "weather", "value": ""},
                {"type": "style", "value": ""},
                {"type": "people", "value": str(self.questionnaire.get("nombre_voyageurs", 2))},
                {"type": "activities", "value": str(num_steps)},
                {"type": "cities", "value": "1"}
            ]
        })

        logger.info(f"🏗️ Structure JSON initialisée: {code}")
        logger.info(f"   - Destination: {destination}")
        logger.info(f"   - Jours: {total_days}")
        logger.info(f"   - Rythme: {rhythm}")
        logger.info(f"   - Steps: {num_steps} activités + 1 summary")

    # =========================================================================
    # TRIP-LEVEL SETTERS (pour enrichir le trip principal)
    # =========================================================================

    def set_hero_image(self, url: str) -> None:
        """Définir l'image hero du trip."""
        if not url or url == "":
            logger.warning("⚠️ Hero image vide fournie, appel MCP...")
            url = self._generate_hero_image_via_mcp()

        self.trip_json["main_image"] = url  # 🔧 FIX: Accès direct
        logger.info(f"🖼️ Hero image définie: {url[:80] if url else 'N/A'}")

    def set_flight_info(
        self,
        flight_from: str,
        flight_to: str,
        duration: str = "",
        flight_type: str = "",
        price: str = "",
    ) -> None:
        """Définir les informations de vol."""
        self.trip_json["flight_from"] = flight_from  # 🔧 FIX: Accès direct
        self.trip_json["flight_to"] = flight_to
        if duration:
            self.trip_json["flight_duration"] = duration
        if flight_type:
            self.trip_json["flight_type"] = flight_type
        if price:
            self.trip_json["price_flights"] = price
        logger.info(f"✈️ Vol défini: {flight_from} → {flight_to}")

    def set_hotel_info(
        self,
        hotel_name: str,
        hotel_rating: float = 0,
        price: str = "",
    ) -> None:
        """Définir les informations d'hébergement."""
        self.trip_json["hotel_name"] = hotel_name  # 🔧 FIX: Accès direct
        if hotel_rating:
            self.trip_json["hotel_rating"] = hotel_rating
        if price:
            self.trip_json["price_hotels"] = price
        logger.info(f"🏨 Hébergement défini: {hotel_name} ({hotel_rating}⭐)" if hotel_rating else f"🏨 Hébergement défini: {hotel_name}")

    def set_prices(
        self,
        total_price: str = "",
        price_flights: str = "",
        price_hotels: str = "",
        price_transport: str = "",
        price_activities: str = "",
    ) -> None:
        """Définir les prix."""
        if total_price:
            self.trip_json["total_price"] = total_price  # 🔧 FIX: Accès direct
            self.trip_json["total_budget"] = total_price
        if price_flights:
            self.trip_json["price_flights"] = price_flights
        if price_hotels:
            self.trip_json["price_hotels"] = price_hotels
        if price_transport:
            self.trip_json["price_transport"] = price_transport
        if price_activities:
            self.trip_json["price_activities"] = price_activities

        if total_price:
            logger.info(f"💰 Budget défini: {total_price}")

    def set_weather(self, average_weather: str) -> None:
        """Définir la météo moyenne."""
        if average_weather:
            self.trip_json["average_weather"] = average_weather  # 🔧 FIX: Accès direct
            logger.info(f"🌤️ Météo moyenne définie: {average_weather}")

    def set_travel_style(self, style: str, style_en: str = "") -> None:
        """Définir le style de voyage."""
        if style:
            self.trip_json["travel_style"] = style  # 🔧 FIX: Accès direct
            self.trip_json["travel_style_en"] = style_en or style
            logger.info(f"🎨 Style défini: {style}")

    # =========================================================================
    # STEP-LEVEL SETTERS (pour enrichir chaque step)
    # =========================================================================

    def set_step_title(
        self,
        step_number: int,
        title: str,
        title_en: str = "",
        subtitle: str = "",
        subtitle_en: str = "",
    ) -> None:
        """Définir le titre d'une step."""
        step = self._get_step(step_number)
        step["title"] = title
        step["title_en"] = title_en or title
        if subtitle:
            step["subtitle"] = subtitle
        if subtitle_en:
            step["subtitle_en"] = subtitle_en or subtitle
        logger.info(f"📝 Step {step_number}: Titre défini '{title}'")

    def set_step_image(self, step_number: int, image_url: str) -> None:
        """
        Définir l'image d'une step.

        Si l'image est vide ou invalide, appeler images.background() directement.

        Args:
            step_number: Numéro de la step
            image_url: URL de l'image (Supabase idéalement)
        """
        step = self._get_step(step_number)

        # Vérifier si l'image est valide (Supabase)
        if image_url and "supabase.co" in image_url and "FAILED" not in image_url.upper():
            step["main_image"] = image_url
            logger.info(f"🖼️ Step {step_number}: Image définie (Supabase)")
        else:
            # Appel MCP direct en fallback
            logger.warning(f"⚠️ Step {step_number}: Image invalide/vide, appel MCP...")
            destination = self.trip_json["destination"]
            step_title = step.get("title") or f"Activity {step_number}"
            prompt = f"{step_title} in {destination}"

            mcp_image = self._call_mcp_images_background(prompt=prompt)

            if mcp_image and "supabase.co" in mcp_image:
                step["main_image"] = mcp_image
                logger.info(f"✅ Step {step_number}: Image générée via MCP")
            else:
                # Fallback Unsplash
                fallback_url = self._build_fallback_image(step.get("title") or "travel")
                step["main_image"] = fallback_url
                logger.warning(f"⚠️ Step {step_number}: Fallback Unsplash")

    def set_step_gps(
        self,
        step_number: int,
        latitude: float,
        longitude: float,
    ) -> None:
        """Définir les coordonnées GPS d'une step."""
        step = self._get_step(step_number)
        step["latitude"] = latitude
        step["longitude"] = longitude
        logger.info(f"📍 Step {step_number}: GPS défini ({latitude:.4f}, {longitude:.4f})")

    def set_step_content(
        self,
        step_number: int,
        why: str = "",
        why_en: str = "",
        tips: str = "",
        tips_en: str = "",
        transfer: str = "",
        transfer_en: str = "",
        suggestion: str = "",
        suggestion_en: str = "",
    ) -> None:
        """Définir le contenu textuel d'une step."""
        step = self._get_step(step_number)
        if why:
            step["why"] = why
        if why_en:
            step["why_en"] = why_en
        if tips:
            step["tips"] = tips
        if tips_en:
            step["tips_en"] = tips_en
        if transfer:
            step["transfer"] = transfer
        if transfer_en:
            step["transfer_en"] = transfer_en
        if suggestion:
            step["suggestion"] = suggestion
        if suggestion_en:
            step["suggestion_en"] = suggestion_en

        logger.debug(f"📄 Step {step_number}: Contenu mis à jour")

    def set_step_weather(
        self,
        step_number: int,
        icon: str,
        temp: str,
        description: str = "",
        description_en: str = "",
    ) -> None:
        """Définir la météo d'une step."""
        step = self._get_step(step_number)
        step["weather_icon"] = icon
        step["weather_temp"] = temp
        if description:
            step["weather_description"] = description
        if description_en:
            step["weather_description_en"] = description_en

        logger.debug(f"🌤️ Step {step_number}: Météo définie ({icon}, {temp})")

    def set_step_price_duration(
        self,
        step_number: int,
        price: float = 0,
        duration: str = "",
    ) -> None:
        """Définir le prix et la durée d'une step."""
        step = self._get_step(step_number)
        if price:
            step["price"] = price
        if duration:
            step["duration"] = duration

        logger.debug(f"💰 Step {step_number}: Prix/durée définis")

    def set_step_type(self, step_number: int, step_type: str) -> None:
        """Définir le type d'une step (activity, restaurant, transport, etc.)."""
        if step_type:
            step = self._get_step(step_number)
            step["step_type"] = step_type
            logger.debug(f"🏷️ Step {step_number}: Type défini ({step_type})")

    # =========================================================================
    # SUMMARY STATS
    # =========================================================================

    def update_summary_stats(self) -> None:
        """Mettre à jour les summary_stats de la step summary."""
        try:
            summary_step = self._get_summary_step()
            trip = self.trip_json

            # Calculer les activités (steps hors summary)
            activities_count = len([s for s in self.trip_json["steps"] if not s.get("is_summary", False)])

            # Extraire le style du questionnaire
            ambiance = self.questionnaire.get("ambiance_voyage", "")
            style_mapping = {
                "relaxation": ("Détente", "Relaxation"),
                "adventure": ("Aventure", "Adventure"),
                "culture": ("Culture", "Culture"),
                "nature": ("Nature", "Nature"),
            }
            style_fr, style_en = style_mapping.get(ambiance, (ambiance.title() if ambiance else "", ambiance.title() if ambiance else ""))

            summary_step["summary_stats"] = [
                {"type": "days", "value": str(trip["total_days"])},
                {"type": "budget", "value": trip["total_price"] or trip["total_budget"] or ""},
                {"type": "weather", "value": trip["average_weather"] or ""},
                {"type": "style", "value": style_fr or trip["travel_style"] or ""},
                {"type": "people", "value": str(trip["travelers"])},
                {"type": "activities", "value": str(activities_count)},
                {"type": "cities", "value": "1"},
            ]

            logger.info(f"📊 Summary stats mis à jour: {len(summary_step['summary_stats'])} stats")
        except Exception as e:
            logger.error(f"❌ Erreur lors de la mise à jour des summary stats: {e}")

    # =========================================================================
    # GETTERS & UTILITIES
    # =========================================================================

    def get_json(self) -> Dict[str, Any]:
        """
        Retourner le JSON complet (sans wrapper).

        Returns:
            Dict avec la structure du trip
        """
        return self.trip_json  # 🔧 FIX: Pas de wrapper "trip"

    def get_current_state_yaml(self) -> str:
        """
        Retourner l'état courant en YAML pour le passer aux agents.

        Les agents peuvent voir ce qui a déjà été rempli et ce qui manque.
        """
        try:
            return yaml.dump(self.trip_json, allow_unicode=True, sort_keys=False, default_flow_style=False)
        except Exception as e:
            logger.error(f"❌ Erreur lors de la conversion YAML: {e}")
            return "{}"

    def get_completeness_report(self) -> Dict[str, Any]:
        """
        Générer un rapport de complétude pour debug/validation.

        Returns:
            Dict avec:
            - trip_completeness: % de champs trip remplis
            - steps_with_title: Nombre de steps avec titre
            - steps_with_image: Nombre de steps avec image
            - steps_with_gps: Nombre de steps avec GPS
            - missing_critical: Liste des champs critiques manquants
        """
        trip = self.trip_json
        steps = [s for s in self.trip_json["steps"] if not s.get("is_summary", False)]

        # Trip-level completeness
        trip_fields_filled = sum([1 for v in trip.values() if v and v != "" and v != 0])
        trip_total_fields = len(trip)
        trip_completeness = (trip_fields_filled / trip_total_fields) * 100

        # Steps completeness
        steps_with_title = sum([1 for s in steps if s.get("title") and s["title"] != ""])
        steps_with_image = sum([1 for s in steps if s.get("main_image") and s["main_image"] != ""])
        steps_with_gps = sum([1 for s in steps if s.get("latitude") != 0 and s.get("longitude") != 0])

        report = {
            "trip_completeness": f"{trip_completeness:.1f}%",
            "steps_with_title": f"{steps_with_title}/{len(steps)}",
            "steps_with_image": f"{steps_with_image}/{len(steps)}",
            "steps_with_gps": f"{steps_with_gps}/{len(steps)}",
            "missing_critical": self._find_missing_critical_fields(),
        }

        logger.info(f"📊 Rapport de complétude:")
        logger.info(f"   - Trip: {report['trip_completeness']}")
        logger.info(f"   - Steps avec titre: {report['steps_with_title']}")
        logger.info(f"   - Steps avec image: {report['steps_with_image']}")
        logger.info(f"   - Steps avec GPS: {report['steps_with_gps']}")
        if report['missing_critical']:
            logger.warning(f"   - Champs critiques manquants: {len(report['missing_critical'])}")

        return report

    def _get_step(self, step_number: int) -> Dict[str, Any]:
        """Récupérer une step par son numéro."""
        for step in self.trip_json["steps"]:
            if step["step_number"] == step_number:
                return step
        raise ValueError(f"Step {step_number} not found")

    def _get_summary_step(self) -> Dict[str, Any]:
        """Récupérer la step summary."""
        for step in self.trip_json["steps"]:
            if step.get("is_summary", False):
                return step
        raise ValueError("Summary step not found")

    def _calculate_total_days(self, start_date: str) -> int:
        """Calculer le nombre total de jours."""
        # Essayer depuis questionnaire
        duree_str = self.questionnaire.get("duree", "")
        match = re.search(r'(\d+)', str(duree_str))
        if match:
            days = int(match.group(1))
            logger.debug(f"📅 Jours calculés depuis questionnaire: {days}")
            return days

        # Défaut
        logger.warning("⚠️ Durée non trouvée, utilisation de 7 jours par défaut")
        return 7

    def _calculate_steps_count(self, total_days: int, rhythm: str) -> int:
        """
        Calculer le nombre de steps selon le rythme.

        - relaxed: 1-2 steps/jour → 1.5 steps/jour en moyenne
        - balanced: 1-2 steps/jour → 1.5 steps/jour en moyenne
        - intense: 2-3 steps/jour → 2.5 steps/jour en moyenne
        """
        multipliers = {
            "relaxed": 1.5,
            "balanced": 1.5,
            "intense": 2.5,
        }

        multiplier = multipliers.get(rhythm, 1.5)
        steps_count = max(3, int(total_days * multiplier))

        logger.debug(f"📋 Steps calculés: {total_days} jours × {multiplier} = {steps_count} steps")
        return steps_count

    def _calculate_day_number(self, step_number: int, total_steps: int, total_days: int) -> int:
        """Calculer le numéro du jour pour une step donnée."""
        # Distribution équitable des steps sur les jours
        steps_per_day = total_steps / total_days
        day = min(total_days, max(1, int((step_number - 1) / steps_per_day) + 1))
        return day

    def _generate_code(self, destination: str) -> str:
        """Générer un code unique pour le trip (max 20 chars)."""
        # Pattern: DEST-YYYY-UUID (ex: AMSTERDA-2025-A1B2C3)
        # DEST: max 8 chars
        # YYYY: 4 chars
        # UUID: 6 chars
        # Separators: 2 chars
        # Total: 8+4+6+2 = 20 chars
        clean_dest = re.sub(r'[^A-Z0-9]', '', destination.upper().split(',')[0])[:8]
        year = datetime.utcnow().year
        unique_id = str(uuid.uuid4())[:6].upper()
        code = f"{clean_dest}-{year}-{unique_id}"
        logger.debug(f"🔑 Code généré: {code}")
        return code

    def _generate_hero_image_via_mcp(self) -> str:
        """Générer l'image hero via MCP si elle est manquante."""
        try:
            destination = self.trip_json["destination"]
            trip_code = self.trip_json["code"]
            prompt = f"hero image for {destination}, spectacular, travel photography"

            for tool in self.mcp_tools:
                if hasattr(tool, 'name') and tool.name == "images.hero":
                    result = tool.func(
                        trip_code=trip_code,
                        prompt=prompt,
                    )
                    if result and "supabase.co" in result:
                        logger.info(f"✅ Hero image générée via MCP: {result[:80]}")
                        return result
        except Exception as e:
            logger.error(f"❌ Erreur génération hero image via MCP: {e}")

        # Fallback Unsplash
        fallback = self._build_fallback_image(self.trip_json["destination"], is_hero=True)
        logger.warning(f"⚠️ Hero image fallback Unsplash: {fallback[:80]}")
        return fallback

    def _call_mcp_images_background(
        self,
        prompt: str,
    ) -> Optional[str]:
        """Appeler images.background MCP directement."""
        try:
            trip_code = self.trip_json["code"]

            for tool in self.mcp_tools:
                if hasattr(tool, 'name') and tool.name == "images.background":
                    result = tool.func(
                        trip_code=trip_code,
                        prompt=prompt,
                    )
                    return result
        except Exception as e:
            logger.error(f"❌ MCP images.background failed: {e}")

        return None

    def _build_fallback_image(self, query: str, is_hero: bool = False) -> str:
        """Construire une URL Unsplash fallback."""
        clean_query = re.sub(r'[^a-zA-Z0-9\s]', '', query).strip().replace(' ', '%20')

        if is_hero:
            return f"https://source.unsplash.com/1920x1080/?{clean_query},travel,destination"
        else:
            return f"https://source.unsplash.com/800x600/?{clean_query},travel,activity"

    def _find_missing_critical_fields(self) -> List[str]:
        """Identifier les champs critiques manquants."""
        missing = []
        trip = self.trip_json

        if not trip.get("main_image") or trip["main_image"] == "":
            missing.append("trip.main_image")
        if not trip.get("total_price") and not trip.get("total_budget"):
            missing.append("trip.total_price")

        steps = [s for s in self.trip_json["steps"] if not s.get("is_summary", False)]
        for step in steps:
            step_num = step["step_number"]
            if not step.get("title") or step["title"] == "":
                missing.append(f"step_{step_num}.title")
            if not step.get("main_image") or step["main_image"] == "":
                missing.append(f"step_{step_num}.main_image")

        return missing
