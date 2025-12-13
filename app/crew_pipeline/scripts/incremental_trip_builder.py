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

        # 🆕 PERFORMANCE: Cache pour accès O(1) aux steps (au lieu de O(n))
        self._steps_cache: Dict[int, Dict[str, Any]] = {}

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

        # 🆕 PERFORMANCE: Construire le cache après création des steps
        self._rebuild_steps_cache()

        logger.info(f"🏗️ Structure JSON initialisée: {code}")
        logger.info(f"   - Destination: {destination}")
        logger.info(f"   - Jours: {total_days}")
        logger.info(f"   - Rythme: {rhythm}")
        logger.info(f"   - Steps: {num_steps} activités + 1 summary")
        logger.info(f"   - Cache size: {len(self._steps_cache)} entries")

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

    # =========================================================================
    # SETTERS (PHASE 2 & 3)
    # =========================================================================

    def set_flight_info(
        self,
        flight_from: str = "",
        flight_to: str = "",
        duration: str = "",
        flight_type: str = "",
        price: str = "",
    ) -> None:
        """Enrichir le trip avec les infos vol."""
        if flight_from:
            self.trip_json["flight_from"] = flight_from
        if flight_to:
            self.trip_json["flight_to"] = flight_to
        if duration:
            self.trip_json["flight_duration"] = duration
        if flight_type:
            self.trip_json["flight_type"] = flight_type
        
        # On ne traite pas `price` ici car set_prices() le fait mieux en Phase 3
        logger.info(f"✈️ Flight info updated: {flight_from} -> {flight_to}")

    def set_hotel_info(
        self,
        hotel_name: str = "",
        hotel_rating: float = 0.0,
        price: str = "",
    ) -> None:
        """Enrichir le trip avec les infos hôtel."""
        if hotel_name:
            self.trip_json["hotel_name"] = hotel_name
        if hotel_rating:
            self.trip_json["hotel_rating"] = hotel_rating
            
        # On ne traite pas `price` ici car set_prices() le fait mieux en Phase 3
        logger.info(f"🏨 Hotel info updated: {hotel_name} ({hotel_rating})")

    def set_step_gps(self, step_number: int, latitude: float, longitude: float) -> None:
        """Définir les coordonnées GPS d'une step."""
        step = self._get_step(step_number)
        if step:
            step["latitude"] = latitude
            step["longitude"] = longitude
            logger.debug(f"📍 Step {step_number}: GPS updated")

    def set_step_title(self, step_number: int, title: str, title_en: str = "", subtitle: str = "", subtitle_en: str = "") -> None:
        """Définir les titres et sous-titres d'une step."""
        step = self._get_step(step_number)
        if step:
            step["title"] = title
            step["title_en"] = title_en
            step["subtitle"] = subtitle
            step["subtitle_en"] = subtitle_en
            logger.debug(f"📝 Step {step_number}: Title set to '{title}'")

    def set_step_content(self, step_number: int, why: str = "", why_en: str = "", tips: str = "", tips_en: str = "", 
                         transfer: str = "", transfer_en: str = "", suggestion: str = "", suggestion_en: str = "") -> None:
        """Définir le contenu détaillé d'une step."""
        step = self._get_step(step_number)
        if step:
            step["why"] = why
            step["why_en"] = why_en
            step["tips"] = tips
            step["tips_en"] = tips_en
            step["transfer"] = transfer
            step["transfer_en"] = transfer_en
            step["suggestion"] = suggestion
            step["suggestion_en"] = suggestion_en
            logger.debug(f"📝 Step {step_number}: Content details updated")

    def set_step_weather(self, step_number: int, icon: str, temp: str, description: str, description_en: str) -> None:
        """Définir la météo pour une step."""
        step = self._get_step(step_number)
        if step:
            step["weather_icon"] = icon
            step["weather_temp"] = temp
            step["weather_description"] = description
            step["weather_description_en"] = description_en
            logger.debug(f"☀️ Step {step_number}: Weather updated")

    def set_step_price_duration(self, step_number: int, price: float, duration: str) -> None:
        """Définir prix et durée d'une step."""
        step = self._get_step(step_number)
        if step:
            step["price"] = price
            step["duration"] = duration

    def set_step_type(self, step_number: int, step_type: str) -> None:
        """Définir le type d'activité."""
        step = self._get_step(step_number)
        if step:
            step["step_type"] = step_type

    def get_completeness_report(self) -> Dict[str, Any]:
        """Générer un rapport de complétude du trip."""
        steps = [s for s in self.trip_json["steps"] if not s.get("is_summary")]
        total_steps = len(steps)
        if total_steps == 0:
            return {"trip_completeness": 0, "steps_with_title": "0/0", "missing_critical": ["No steps"]}

        with_title = len([s for s in steps if s.get("title")])
        with_image = len([s for s in steps if s.get("main_image")])
        with_gps = len([s for s in steps if s.get("latitude") and s.get("longitude")])
        
        missing = self._find_missing_critical_fields()
        
        return {
            "trip_completeness": f"{int((with_title/total_steps)*100)}%",
            "steps_with_title": f"{with_title}/{total_steps}",
            "steps_with_image": f"{with_image}/{total_steps}",
            "steps_with_gps": f"{with_gps}/{total_steps}",
            "missing_critical": missing
        }

    def set_step_details(self, step_number: int, **kwargs) -> None:
        """
        Mettre à jour les champs textuels d'une step.
        """
        step = self._get_step(step_number)
        if not step:
            return
            
        # Update allowed fields
        allowed = ["title", "title_en", "subtitle", "subtitle_en", "why", "why_en",
                  "tips", "tips_en", "transfer", "transfer_en", "suggestion", "suggestion_en",
                  "weather_temp", "weather_description", "weather_description_en",
                  "duration", "step_type"]
                  
        for k, v in kwargs.items():
            if k in allowed:
                step[k] = v
        
        logger.debug(f"📝 Step {step_number}: details updated")

    def set_prices(
        self,
        total_price: float,
        price_flights: float,
        price_hotels: float,
        price_transport: float = 0,
        price_activities: float = 0,
        currency: str = "EUR"
    ) -> None:
        """Définir les prix finaux du voyage."""
        self.trip_json["total_price"] = total_price
        self.trip_json["price_flights"] = price_flights
        self.trip_json["price_hotels"] = price_hotels
        self.trip_json["price_transport"] = price_transport
        self.trip_json["price_activities"] = price_activities
        # self.trip_json["currency"] = currency # Check if needed in schema

        # Update summary stats budget
        self._update_stat("budget", f"{total_price} {currency}")
        logger.info(f"💰 Prices updated: Total {total_price} {currency}")

    def update_summary_stats(self) -> None:
        """
        Recalculer les stats du résumé (étape 99).
        Appelé à la fin pour être sûr que tout est synchro.
        """
        summary_step = self._get_step(99)
        if not summary_step:
            return

        # Days
        self._update_stat("days", str(self.trip_json.get("total_days", 7)))
        
        # Budget
        total = self.trip_json.get("total_price")
        if total:
            self._update_stat("budget", f"{total} EUR")
            
        # Travelers
        travelers = self.questionnaire.get("nombre_voyageurs", 2)
        self._update_stat("people", str(travelers))
        
        # Activities count (steps - summary)
        steps_count = len([s for s in self.trip_json["steps"] if not s.get("is_summary")])
        self._update_stat("activities", str(steps_count))

        logger.info("📊 Summary stats updated")

    def _update_stat(self, stat_type: str, value: str) -> None:
        """Helper pour mettre à jour une stat spécifique."""
        summary_step = self._get_step(99)
        if not summary_step:
            return
            
        stats = summary_step.get("summary_stats", [])
        updated = False
        for stat in stats:
            if stat["type"] == stat_type:
                stat["value"] = value
                updated = True
                break
        
        if not updated:
            stats.append({"type": stat_type, "value": value})

    def _rebuild_steps_cache(self) -> None:
        """
        🆕 PERFORMANCE: Reconstruit le cache d'accès rapide aux steps.

        Appelé après toute modification de self.trip_json["steps"]
        (ajout, suppression, réorganisation).

        Complexité : O(n) une fois, puis O(1) pour tous les accès.
        """
        self._steps_cache.clear()

        if self.trip_json and "steps" in self.trip_json:
            for step in self.trip_json["steps"]:
                step_number = step.get("step_number")
                if step_number is not None:
                    self._steps_cache[step_number] = step

        logger.debug(f"🔄 Steps cache rebuilt: {len(self._steps_cache)} entries")

    def _get_step(self, step_number: int) -> Optional[Dict[str, Any]]:
        """
        🚀 PERFORMANCE: Récupérer une step par son numéro (O(1) grâce au cache).

        Args:
            step_number: Numéro de la step (1-N ou 99 pour summary)

        Returns:
            Dict de la step ou None si non trouvée
        """
        step = self._steps_cache.get(step_number)

        if step is None:
            logger.warning(f"⚠️ Step {step_number} not found in cache")

        return step

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

    # =========================================================================
    # EXPORT / PUBLIC ACCESSORS
    # =========================================================================

    def get_current_state_yaml(self) -> str:
        """Retourne l'état actuel du trip au format YAML pour les logs."""
        try:
            return yaml.dump(self.trip_json, allow_unicode=True, sort_keys=False)
        except Exception as e:
            return f"Error dumping YAML: {e}"

    def get_json(self) -> Dict[str, Any]:
        """Retourne le trip JSON final."""
        return self.trip_json

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
