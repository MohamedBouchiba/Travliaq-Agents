"""
StepTemplateGenerator - Génère templates de steps avec GPS et images pré-remplies

Ce script offload le travail technique de l'Agent 6 (Itinerary Designer):
- Appelle geo.place pour obtenir GPS de chaque step
- Appelle images.background pour obtenir images Supabase (via ImageGenerator)
- Génère structure complète que l'Agent 6 n'a plus qu'à enrichir textuellement

Gains attendus:
- Fiabilité GPS/images: 100% (vs 60-75% avec Agent 6)
- Réduction charge Agent 6: -50% 
- Temps Agent 6: -40%
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from app.crew_pipeline.scripts.image_generator import ImageGenerator

logger = logging.getLogger(__name__)


class StepTemplateGenerator:
    """
    Générateur de templates de steps pour alléger le travail de l'Agent 6.
    
    Workflow:
    1. Reçoit le plan structurel (Agent 5)
    2. Pour chaque step prévue:
       - Recherche GPS via geo.place
       - Génère image via ImageGenerator (Centralisé)
       - Crée template avec structure complète
    3. Retourne liste de templates que l'Agent 6 complète (contenu textuel)
    """
    
    def __init__(self, mcp_tools: Any):
        """
        Initialiser avec accès aux outils MCP.
        
        Args:
            mcp_tools: Instance MCPToolManager avec accès à geo.*, images.*, etc.
        """
        self.mcp_tools = mcp_tools
        self.image_gen = ImageGenerator(mcp_tools)
        self.templates_generated = []
    
    def generate_templates(
        self,
        trip_structure_plan: Dict[str, Any],
        destination: str,
        destination_country: str,
        trip_code: str,
        parallel: bool = True,
        max_workers: int = 6,
    ) -> List[Dict[str, Any]]:
        """
        Générer templates de steps avec GPS et images pré-remplies.

        Args:
            trip_structure_plan: Plan structurel de l'Agent 5
            destination: Destination du voyage
            destination_country: Pays de destination
            trip_code: Code unique du trip
            parallel: Si True, génère en parallèle (défaut)
            max_workers: Nombre max de threads parallèles
        """
        logger.info(f"🏗️ Generating step templates for {destination}, {destination_country} (parallel={parallel})")

        # Parser le plan structurel
        daily_distribution = trip_structure_plan.get("daily_distribution", [])
        priority_activity_types = trip_structure_plan.get("priority_activity_types", [])
        zones_coverage = trip_structure_plan.get("zones_coverage", [])

        if not daily_distribution:
            logger.error("❌ Plan structurel manquant daily_distribution")
            return []

        if not priority_activity_types:
            priority_activity_types = ["culture", "gastronomy", "sightseeing"]
            logger.warning(f"⚠️ Priority activity types manquants, utilisation fallback: {priority_activity_types}")

        # Créer mapping zone -> activity types pour chaque jour
        zone_activities = self._map_zones_to_activities(zones_coverage, priority_activity_types)

        # Construire liste de toutes les steps à générer
        step_tasks = []
        step_number = 1

        for day_plan in daily_distribution:
            day = day_plan.get("day", step_number)
            steps_count = day_plan.get("steps_count", 1)
            zone = day_plan.get("zone", destination)

            logger.info(f"📅 Jour {day}: {steps_count} steps dans zone '{zone}'")

            for step_index in range(steps_count):
                activity_type = priority_activity_types[step_number % len(priority_activity_types)]

                step_tasks.append({
                    "step_number": step_number,
                    "day_number": day,
                    "zone": zone,
                    "activity_type": activity_type,
                    "destination": destination,
                    "destination_country": destination_country,
                    "trip_code": trip_code,
                })
                step_number += 1

        # Générer templates en parallèle ou séquentiellement
        if parallel and len(step_tasks) > 1:
            templates = self._generate_templates_parallel(step_tasks, max_workers)
        else:
            templates = self._generate_templates_sequential(step_tasks)

        # 🔧 FIX: Ne PAS créer summary step ici - IncrementalTripBuilder l'a déjà créée (step 99)

        logger.info(f"✅ {len(templates)} templates générés (activités seulement, summary step déjà existante)")
        self.templates_generated = templates

        return templates

    def _generate_templates_sequential(
        self,
        step_tasks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Génération séquentielle des templates (méthode originale)."""
        templates = []

        for task in step_tasks:
            template = self._generate_single_step_template(**task)
            if template:
                templates.append(template)
            else:
                logger.warning(f"⚠️ Échec génération template step {task['step_number']}, skip")

        return templates

    def _generate_templates_parallel(
        self,
        step_tasks: List[Dict[str, Any]],
        max_workers: int
    ) -> List[Dict[str, Any]]:
        """Génération parallèle des templates avec ThreadPoolExecutor."""
        logger.info(f"⚡ Generating {len(step_tasks)} templates in parallel (max_workers={max_workers})")

        templates = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Soumettre toutes les générations
            future_to_task = {
                executor.submit(self._generate_single_step_template, **task): task
                for task in step_tasks
            }

            # Collecter résultats au fur et à mesure
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                step_num = task["step_number"]

                try:
                    template = future.result()
                    if template:
                        templates.append(template)
                        logger.debug(f"  ✅ Template step {step_num} generated")
                    else:
                        logger.warning(f"  ⚠️ Template step {step_num} generation failed")
                except Exception as e:
                    logger.error(f"  ❌ Template step {step_num} generation error: {e}")

        # Trier par step_number
        templates.sort(key=lambda t: t.get("step_number", 0))

        return templates
    
    def _generate_single_step_template(
        self,
        step_number: int,
        day_number: int,
        zone: str,
        activity_type: str,
        destination: str,
        destination_country: str,
        trip_code: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Générer template pour UNE step avec GPS et image.
        
        Workflow:
        1. Construire query geo.place optimale
        2. Appeler geo.place pour GPS
        3. Appeler ImageGenerator pour image Supabase
        4. Retourner template complet
        """
        logger.info(f"  🔨 Generating template step {step_number}: {activity_type} in {zone}")
        
        # 1. RECHERCHE GPS via geo.place
        gps_data = self._fetch_gps_for_activity(
            activity_type=activity_type,
            zone=zone,
            destination=destination,
            destination_country=destination_country,
        )
        
        if not gps_data:
            logger.error(f"    ❌ GPS fetch failed for step {step_number}")
            return None
        
        latitude = gps_data.get("latitude", 0)
        longitude = gps_data.get("longitude", 0)
        place_name = gps_data.get("name", "")
        
        # 2. GÉNÉRATION IMAGE via ImageGenerator (robuste)
        image_url = self.image_gen.generate_step_image(
            step_number=step_number,
            title=f"visiting {place_name}",
            destination=f"{destination}, {destination_country}",
            trip_code=trip_code,
            activity_type=activity_type
        )
        
        # 3. CRÉER TEMPLATE
        template = {
            # Identifiants
            "step_number": step_number,
            "day_number": day_number,
            "is_summary": False,
            
            # Données techniques PRÉ-REMPLIES (script)
            "latitude": latitude,
            "longitude": longitude,
            "main_image": image_url,
            "step_type": self._map_activity_to_step_type(activity_type),
            
            # Métadonnées pré-remplies
            "price": 0,  # Agent 6 ajustera
            "duration": "",  # Agent 6 remplira
            "images": [],
            
            # Météo (Agent 6 complétera)
            "weather_icon": None,
            "weather_temp": "",
            "weather_description": "",
            "weather_description_en": "",
            
            # Champs VIDES à remplir par Agent 6 (CONTENU)
            "title": "",
            "title_en": "",
            "subtitle": "",
            "subtitle_en": "",
            "why": "",
            "why_en": "",
            "tips": "",
            "tips_en": "",
            "transfer": "",
            "transfer_en": "",
            "suggestion": "",
            "suggestion_en": "",
        }
        
        logger.info(f"    ✅ Template created: GPS ({latitude:.4f}, {longitude:.4f}), Image: {bool(image_url)}")
        
        return template
    
    def _fetch_gps_for_activity(
        self,
        activity_type: str,
        zone: str,
        destination: str,
        destination_country: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Rechercher GPS pour une activité via geo.place.
        
        Stratégie:
        1. Essayer query spécifique: "[activity_type] [zone], [destination], [country]"
        2. Si échec, essayer query large: "[zone], [destination]"
        3. Si échec, fallback centre ville: "[destination], [country]"
        """
        # Attempt 1: Query spécifique
        query_specific = f"{activity_type} {zone}, {destination}, {destination_country}"
        
        try:
            logger.debug(f"      🔍 geo.place('{query_specific}')")
            results = self.mcp_tools.call_tool("geo.place", query=query_specific, max_results=1)
            
            if results and len(results) > 0:
                logger.debug(f"      ✅ GPS found (SPECIFIC): {results[0].get('name')} in {results[0].get('country')}")
                return results[0]
        except Exception as e:
            logger.warning(f"      ⚠️ geo.place failed attempt 1: {e}")
        
        # Attempt 2: Query zone
        query_zone = f"{zone}, {destination}, {destination_country}"
        
        try:
            logger.debug(f"      🔍 geo.place('{query_zone}')")
            results = self.mcp_tools.call_tool("geo.place", query=query_zone, max_results=1)
            
            if results and len(results) > 0:
                logger.debug(f"      ✅ GPS found (zone fallback): {results[0].get('name')}")
                return results[0]
        except Exception as e:
            logger.warning(f"      ⚠️ geo.place failed attempt 2: {e}")
        
        # Attempt 3: Fallback centre ville
        query_city = f"{destination}, {destination_country}"
        
        try:
            logger.debug(f"      🔍 geo.city('{query_city}')")
            results = self.mcp_tools.call_tool("geo.city", query=query_city, max_results=1)
            
            if results and len(results) > 0:
                logger.debug(f"      ✅ GPS found (city fallback): {results[0].get('name')}")
                return results[0]
        except Exception as e:
            logger.error(f"      ❌ All GPS attempts failed: {e}")
        
        return None
    
    def _generate_summary_step(
        self,
        step_number: int,
        total_days: int,
    ) -> Dict[str, Any]:
        """
        Générer step summary (récapitulative).
        
        ⚠️ DEPRECATED: Cette méthode n'est plus utilisée.
        IncrementalTripBuilder crée déjà la step 99 (summary) dans initialize_structure.
        Garder pour référence uniquement.
        """
        return {
            "step_number": step_number,
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
                {"type": "people", "value": ""},
                {"type": "activities", "value": ""},
                {"type": "cities", "value": "1"},
            ],
        }
    
    def _map_zones_to_activities(
        self,
        zones_coverage: List[Dict[str, Any]],
        priority_activity_types: List[str],
    ) -> Dict[str, List[str]]:
        """Mapper chaque zone à ses types d'activités prioritaires."""
        # Pour l'instant retourne mapping simple
        # TODO: Implémenter logique sophistiquée basée sur zones_coverage
        return {}
    
    def _map_activity_to_step_type(self, activity_type: str) -> str:
        """
        Mapper activity_type (culture, gastronomy, etc.) à step_type (visite, restaurant, etc.).
        """
        mapping = {
            "culture": "visite",
            "gastronomy": "gastronomie",
            "nature": "activité",
            "relaxation": "détente",
            "adventure": "activité",
            "nightlife": "sortie",
            "shopping": "shopping",
            "sports": "sport",
        }
        return mapping.get(activity_type.lower(), "activité")
