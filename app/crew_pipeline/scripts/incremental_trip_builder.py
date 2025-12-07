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
            "main_image": None,
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
                "main_image": None,
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
            "main_image": None,
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
        # Si URL vide ou invalide, générer via ImageGenerator
        if not url or url == "" or "supabase.co" not in url:
            logger.warning("⚠️ Hero image vide ou invalide fournie, appel ImageGenerator...")
            
            # Initialiser ImageGenerator si besoin (lazy init si mcp_tools dispo)
            if not hasattr(self, 'image_gen') or not self.image_gen:
                if self.mcp_tools:
                    from app.crew_pipeline.scripts.image_generator import ImageGenerator
                    self.image_gen = ImageGenerator(self.mcp_tools)
                else:
                    logger.error("❌ Impossible d'initialiser ImageGenerator: mcp_tools manquant")
                    return

            url = self.image_gen.generate_hero_image(
                destination=self.trip_json.get("destination", "Travel"),
                trip_code=self.trip_json.get("code", "TRIP")
            )

        self.trip_json["main_image"] = url  # 🔧 FIX: Accès direct
        logger.info(f"🖼️ Hero image définie: {url[:80] if url else 'N/A'}")

    # ... (Keep other setters unchanged) ...

    def set_step_image(self, step_number: int, image_url: str) -> None:
        """
        Définir l'image d'une step.
        """
        step = self._get_step(step_number)

        # Vérifier si l'image est valide (Supabase)
        if image_url and "supabase.co" in image_url and "FAILED" not in image_url.upper():
            step["main_image"] = image_url
            logger.info(f"🖼️ Step {step_number}: Image définie (Supabase)")
        else:
            # Appel ImageGenerator en fallback
            logger.warning(f"⚠️ Step {step_number}: Image invalide/vide, appel ImageGenerator...")
            
            # Initialiser ImageGenerator si besoin
            if not hasattr(self, 'image_gen') or not self.image_gen:
                if self.mcp_tools:
                    from app.crew_pipeline.scripts.image_generator import ImageGenerator
                    self.image_gen = ImageGenerator(self.mcp_tools)
                else:
                    logger.error("❌ Impossible d'initialiser ImageGenerator: mcp_tools manquant")
                    # Fallback ultime
                    step["main_image"] = self._build_fallback_image(step.get("title") or "travel")
                    return

            destination = self.trip_json["destination"]
            step_title = step.get("title") or f"Activity {step_number}"
            
            generated_url = self.image_gen.generate_step_image(
                step_number=step_number,
                title=step_title,
                destination=destination,
                trip_code=self.trip_json.get("code"),
                activity_type=step.get("step_type", "")
            )
            
            step["main_image"] = generated_url
            logger.info(f"✅ Step {step_number}: Image générée via ImageGenerator") # Fixed log message

    def _get_step(self, step_number: int) -> Dict[str, Any]:
        """Récupérer une step par son numéro."""
        for step in self.trip_json["steps"]:
            if step["step_number"] == step_number:
                return step
        return None

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _calculate_total_days(self, start_date_str: str) -> int:
        """Calculer la durée totale à partir du questionnaire ou d'une estimation."""
        # 1. Essayer durée explicite du questionnaire
        duree = self.questionnaire.get("duree")
        if duree:
            match = re.search(r'(\d+)', str(duree))
            if match:
                return int(match.group(1))
        
        # 2. Essayer difference date retour - depart
        if start_date_str:
            end_date_str = self.questionnaire.get("date_retour")
            if end_date_str:
                try:
                    start = datetime.strptime(str(start_date_str), "%Y-%m-%d")
                    end = datetime.strptime(str(end_date_str), "%Y-%m-%d")
                    delta = (end - start).days
                    return max(1, delta)
                except Exception:
                    pass

        return 7  # Valeur par défaut si tout échoue

    def _calculate_steps_count(self, total_days: int, rhythm: str) -> int:
        """Calculer le nombre de steps (activités) selon la durée et le rythme."""
        multipliers = {
            "relaxed": 1.5,
            "balanced": 1.5,
            "intense": 2.5
        }
        mult = multipliers.get(rhythm, 1.5)
        return max(1, int(total_days * mult))

    def _generate_code(self, destination: str) -> str:
        """Générer un code de voyage unique."""
        # Nettoyer destination (garder lettres/chiffres, majuscules)
        clean_dest = re.sub(r'[^A-Z0-9]', '', destination.upper().split(',')[0])[:15]
        year = datetime.utcnow().year
        unique_id = str(uuid.uuid4())[:6].upper()
        return f"{clean_dest}-{year}-{unique_id}"

    def _calculate_day_number(self, step_i: int, total_steps: int, total_days: int) -> int:
        """
        Calculer le jour d'une step pour une distribution homogène.
        Ex: 10 steps sur 5 jours -> 2 steps par jour
        """
        if total_days <= 0:
            return 1
        
        # Distribution simple : step_i / (total_steps / total_days)
        # Mais pour éviter les virgules, on mappe proportionnellement
        day = int((step_i - 1) / total_steps * total_days) + 1
        return min(day, total_days)

    # DELETED: _generate_hero_image_via_mcp
    # DELETED: _call_mcp_images_background

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
