"""
Programmatic Trip JSON Builder

This module provides deterministic JSON construction for trips,
guaranteeing schema conformity and image generation via direct MCP tool calls.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TripJsonBuilder:
    """
    Builder programmatique pour construire le JSON Trip conforme au schéma.

    Ce builder prend tous les outputs des agents de la pipeline et construit
    de manière déterministe le JSON final, en garantissant:
    - Tous les champs requis sont présents
    - Les images sont générées (hero + steps) via appels MCP directs si nécessaire
    - Les coordonnées GPS sont présentes pour chaque step
    - Les summary_stats sont calculés programmatiquement
    - Le JSON est validé contre le schéma
    """

    def __init__(
        self,
        questionnaire: Dict[str, Any],
        trip_context: Dict[str, Any],
        destination_choice: Dict[str, Any],
        flights_research: Dict[str, Any],
        accommodation_research: Dict[str, Any],
        trip_structure_plan: Dict[str, Any],
        itinerary_plan: Dict[str, Any],
        budget_calculation: Dict[str, Any],
        mcp_tools: List[Any],
    ):
        """
        Initialize the builder with all agent outputs.

        Args:
            questionnaire: Normalized questionnaire data
            trip_context: Output from trip_context_builder agent
            destination_choice: Output from destination_strategist agent
            flights_research: Output from flights_specialist agent
            accommodation_research: Output from accommodation_specialist agent
            trip_structure_plan: Output from trip_structure_planner agent
            itinerary_plan: Output from itinerary_designer agent
            budget_calculation: Output from budget_calculator agent
            mcp_tools: List of MCP tools for direct invocation
        """
        self.questionnaire = questionnaire
        self.trip_context = trip_context
        self.destination_choice = destination_choice
        self.flights_research = flights_research
        self.accommodation_research = accommodation_research
        self.trip_structure_plan = trip_structure_plan
        self.itinerary_plan = itinerary_plan
        self.budget_calculation = budget_calculation
        self.mcp_tools = mcp_tools

        logger.info("🏗️ TripJsonBuilder initialized with all agent outputs")

    def build(self) -> Dict[str, Any]:
        """
        Construit le JSON complet avec toutes les garanties.

        Returns:
            Dict with structure: {"trip": {...}, "metadata": {...}}
        """
        logger.info("🚀 Starting programmatic trip JSON construction")

        try:
            trip_json = {
                # ===== REQUIRED FIELDS =====
                "code": self._build_code(),
                "destination": self._build_destination(),
                "total_days": self._build_total_days(),
                "steps": self._build_steps(),

                # ===== OPTIONAL CORE FIELDS =====
                "main_image": self._build_hero_image(),
                "subtitle": self._build_subtitle(),
                "subtitle_en": self._build_subtitle_en(),
                "summary": self._build_summary(),
                "summary_en": self._build_summary_en(),

                # ===== DATES =====
                "start_date": self._build_start_date(),
                "end_date": self._build_end_date(),

                # ===== PRICES =====
                "total_price": self._build_total_price(),
                "flight_price": self._build_flight_price(),
                "hotel_price": self._build_hotel_price(),
                "activities_price": self._build_activities_price(),
                "currency": self._build_currency(),

                # ===== FLIGHTS =====
                "flight_from": self._build_flight_from(),
                "flight_to": self._build_flight_to(),
                "flight_duration": self._build_flight_duration(),
                "flight_type": self._build_flight_type(),
                "flight_company": self._build_flight_company(),

                # ===== ACCOMMODATION =====
                "hotel_name": self._build_hotel_name(),
                "hotel_rating": self._build_hotel_rating(),
                "hotel_district": self._build_hotel_district(),

                # ===== WEATHER =====
                "weather_icon": self._build_weather_icon(),
                "weather_temp": self._build_weather_temp(),
                "best_period": self._build_best_period(),

                # ===== METADATA =====
                "created_at": datetime.utcnow().isoformat() + "Z",
                "user_id": self.questionnaire.get("user_id"),
            }

            # Validate the constructed JSON
            self._validate_schema(trip_json)

            logger.info(f"✅ Trip JSON built successfully: {trip_json['code']}")
            logger.info(f"   - Destination: {trip_json['destination']}")
            logger.info(f"   - Total days: {trip_json['total_days']}")
            logger.info(f"   - Steps count: {len(trip_json['steps'])}")
            logger.info(f"   - Hero image: {trip_json.get('main_image', 'N/A')[:80]}")

            return {"trip": trip_json}

        except Exception as e:
            logger.error(f"❌ Failed to build trip JSON: {e}", exc_info=True)
            return {
                "error": True,
                "error_message": f"TripJsonBuilder failed: {str(e)}",
            }

    # =========================================================================
    # TRIP-LEVEL FIELD BUILDERS
    # =========================================================================

    def _build_code(self) -> str:
        """Generate unique trip code: DESTINATION-YEAR-UUID."""
        destination = self.destination_choice.get("destination_city") or \
                     self.destination_choice.get("destination_name") or \
                     self.destination_choice.get("destination", "TRIP")

        # Clean destination for code (remove spaces, special chars)
        clean_dest = re.sub(r'[^A-Z0-9]', '', destination.upper().split(',')[0])[:15]
        year = datetime.utcnow().year
        unique_id = str(uuid.uuid4())[:6].upper()

        code = f"{clean_dest}-{year}-{unique_id}"
        logger.info(f"📝 Generated trip code: {code}")
        return code

    def _build_destination(self) -> str:
        """Extract destination city/country."""
        destination = self.destination_choice.get("destination_city") or \
                     self.destination_choice.get("destination_name") or \
                     self.destination_choice.get("destination", "Unknown")
        return destination

    def _build_total_days(self) -> int:
        """Calculate total days from duration or step count."""
        # Try from itinerary
        steps = self.itinerary_plan.get("steps", [])
        if steps:
            # Count unique day_numbers (excluding summary step)
            day_numbers = set()
            for step in steps:
                day_num = step.get("day_number")
                if day_num and day_num != 999:
                    day_numbers.add(day_num)
            if day_numbers:
                return len(day_numbers)

        # Try from questionnaire duration
        duration_str = self.questionnaire.get("duree", "")
        match = re.search(r'(\d+)', str(duration_str))
        if match:
            return int(match.group(1))

        return 7  # Default

    def _build_subtitle(self) -> Optional[str]:
        """Build French subtitle."""
        return self.itinerary_plan.get("subtitle")

    def _build_subtitle_en(self) -> Optional[str]:
        """Build English subtitle."""
        return self.itinerary_plan.get("subtitle_en")

    def _build_summary(self) -> Optional[str]:
        """Build French summary."""
        return self.itinerary_plan.get("summary")

    def _build_summary_en(self) -> Optional[str]:
        """Build English summary."""
        return self.itinerary_plan.get("summary_en")

    def _build_start_date(self) -> Optional[str]:
        """Extract start date."""
        date_str = self.questionnaire.get("date_depart") or \
                   self.questionnaire.get("date_depart_approximative")
        if date_str:
            return str(date_str)
        return None

    def _build_end_date(self) -> Optional[str]:
        """Extract end date."""
        return self.questionnaire.get("date_retour")

    def _build_total_price(self) -> Optional[float]:
        """Extract total price from budget calculation."""
        budget = self.budget_calculation.get("total_price") or \
                self.budget_calculation.get("total_budget") or \
                self.budget_calculation.get("estimated_total")

        if budget:
            # Extract numeric value
            if isinstance(budget, (int, float)):
                return float(budget)
            match = re.search(r'(\d+(?:\.\d+)?)', str(budget))
            if match:
                return float(match.group(1))
        return None

    def _build_flight_price(self) -> Optional[float]:
        """Extract flight price."""
        price = self.flights_research.get("estimated_price") or \
                self.flights_research.get("price") or \
                self.budget_calculation.get("flight_cost")

        if price:
            if isinstance(price, (int, float)):
                return float(price)
            match = re.search(r'(\d+(?:\.\d+)?)', str(price))
            if match:
                return float(match.group(1))
        return None

    def _build_hotel_price(self) -> Optional[float]:
        """Extract hotel price."""
        price = self.accommodation_research.get("estimated_price") or \
                self.accommodation_research.get("price") or \
                self.budget_calculation.get("accommodation_cost")

        if price:
            if isinstance(price, (int, float)):
                return float(price)
            match = re.search(r'(\d+(?:\.\d+)?)', str(price))
            if match:
                return float(match.group(1))
        return None

    def _build_activities_price(self) -> Optional[float]:
        """Extract activities price."""
        price = self.budget_calculation.get("activities_cost")

        if price:
            if isinstance(price, (int, float)):
                return float(price)
            match = re.search(r'(\d+(?:\.\d+)?)', str(price))
            if match:
                return float(match.group(1))
        return None

    def _build_currency(self) -> str:
        """Extract currency."""
        return self.budget_calculation.get("currency", "EUR")

    def _build_flight_from(self) -> Optional[str]:
        """Extract departure city."""
        return self.flights_research.get("departure") or \
               self.flights_research.get("from") or \
               self.questionnaire.get("lieu_depart")

    def _build_flight_to(self) -> Optional[str]:
        """Extract arrival city."""
        return self.flights_research.get("arrival") or \
               self.flights_research.get("to") or \
               self._build_destination()

    def _build_flight_duration(self) -> Optional[str]:
        """Extract flight duration."""
        return self.flights_research.get("duration")

    def _build_flight_type(self) -> Optional[str]:
        """Extract flight type (direct/escale)."""
        return self.flights_research.get("type") or \
               self.flights_research.get("flight_type")

    def _build_flight_company(self) -> Optional[str]:
        """Extract airline company."""
        return self.flights_research.get("company") or \
               self.flights_research.get("airline")

    def _build_hotel_name(self) -> Optional[str]:
        """Extract hotel name."""
        return self.accommodation_research.get("name") or \
               self.accommodation_research.get("hotel_name")

    def _build_hotel_rating(self) -> Optional[float]:
        """Extract hotel rating."""
        rating = self.accommodation_research.get("rating") or \
                self.accommodation_research.get("note")

        if rating:
            if isinstance(rating, (int, float)):
                return float(rating)
            match = re.search(r'(\d+(?:\.\d+)?)', str(rating))
            if match:
                return float(match.group(1))
        return None

    def _build_hotel_district(self) -> Optional[str]:
        """Extract hotel district."""
        return self.accommodation_research.get("district") or \
               self.accommodation_research.get("quartier")

    def _build_weather_icon(self) -> Optional[str]:
        """Extract weather icon from destination."""
        return self.destination_choice.get("weather_icon")

    def _build_weather_temp(self) -> Optional[str]:
        """Extract weather temperature."""
        return self.destination_choice.get("weather_temp") or \
               self.destination_choice.get("temperature")

    def _build_best_period(self) -> Optional[str]:
        """Extract best period to visit."""
        return self.destination_choice.get("best_period")

    # =========================================================================
    # HERO IMAGE BUILDER (WITH MCP FALLBACK)
    # =========================================================================

    def _build_hero_image(self) -> str:
        """
        Garantit qu'on a une hero image Supabase.

        Stratégie 3-niveaux:
        1. Chercher dans les outputs agents (itinerary_plan, destination_choice)
        2. Appeler images.hero() directement via MCP
        3. Fallback Unsplash (dernier recours)
        """
        logger.info("🖼️ Building hero image...")

        # Level 1: Try from agent outputs
        hero_candidates = [
            self.itinerary_plan.get("hero_image"),
            self.itinerary_plan.get("main_image"),
            self.destination_choice.get("hero_image"),
            self.destination_choice.get("main_image"),
        ]

        for candidate in hero_candidates:
            if candidate and "supabase.co" in str(candidate):
                logger.info(f"✅ Hero image found from agent: {candidate[:80]}")
                return candidate

        # Level 2: Call MCP tool directly
        logger.warning("⚠️ No hero image from agents, calling MCP tool directly...")
        destination = self._build_destination()
        city = destination.split(',')[0].strip()
        country = destination.split(',')[-1].strip() if ',' in destination else city

        hero_url = self._call_mcp_tool(
            "images.hero",
            city=city,
            country=country,
            trip_code=self._build_code(),
        )

        if hero_url and "supabase.co" in hero_url:
            logger.info(f"✅ Hero image generated via MCP: {hero_url[:80]}")
            return hero_url

        # Level 3: Fallback to Unsplash
        logger.warning("⚠️ MCP hero image failed, using Unsplash fallback")
        return self._build_fallback_image(city, "hero")

    # =========================================================================
    # STEPS BUILDER (CORE LOGIC)
    # =========================================================================

    def _build_steps(self) -> List[Dict[str, Any]]:
        """
        Construit les steps en GARANTISSANT:
        - Chaque step a une image Supabase
        - Chaque step a GPS (latitude/longitude)
        - Tous les champs requis sont présents
        - Les champs bilingues (FR + EN) sont remplis
        - La dernière step est le summary avec summary_stats
        """
        logger.info("📋 Building steps...")

        raw_steps = self.itinerary_plan.get("steps", [])
        if not raw_steps:
            logger.warning("⚠️ No steps found in itinerary_plan")
            return []

        built_steps = []
        destination = self._build_destination()
        city = destination.split(',')[0].strip()
        country = destination.split(',')[-1].strip() if ',' in destination else city
        trip_code = self._build_code()

        for idx, raw_step in enumerate(raw_steps, 1):
            # Check if this is the summary step (day_number = 999 or last step)
            is_summary = raw_step.get("day_number") == 999 or \
                        idx == len(raw_steps) and "summary" in str(raw_step.get("title", "")).lower()

            if is_summary:
                # Build summary step separately
                summary_step = self._build_summary_step(raw_step, idx, trip_code, city, country)
                built_steps.append(summary_step)
            else:
                # Build regular step
                step = self._build_regular_step(raw_step, idx, trip_code, city, country)
                built_steps.append(step)

        logger.info(f"✅ Built {len(built_steps)} steps ({len(built_steps)-1} regular + 1 summary)")
        return built_steps

    def _build_regular_step(
        self,
        raw_step: Dict[str, Any],
        step_number: int,
        trip_code: str,
        city: str,
        country: str,
    ) -> Dict[str, Any]:
        """Build a regular activity step with all fields."""

        step = {
            # ===== REQUIRED FIELDS =====
            "step_number": step_number,
            "day_number": raw_step.get("day_number", (step_number + 1) // 2),  # Estimate if missing
            "title": raw_step.get("title", f"Activité {step_number}"),
            "main_image": self._ensure_step_image(raw_step, step_number, trip_code, city, country),

            # ===== BILINGUAL FIELDS =====
            "title_en": raw_step.get("title_en", raw_step.get("title", "")),
            "subtitle": raw_step.get("subtitle"),
            "subtitle_en": raw_step.get("subtitle_en"),
            "why": raw_step.get("why"),
            "why_en": raw_step.get("why_en"),
            "tips": raw_step.get("tips"),
            "tips_en": raw_step.get("tips_en"),

            # ===== GPS COORDINATES =====
            "latitude": self._ensure_latitude(raw_step, city, country),
            "longitude": self._ensure_longitude(raw_step, city, country),

            # ===== OPTIONAL FIELDS =====
            "duration": raw_step.get("duration"),
            "price": self._extract_price(raw_step.get("price")),
            "transfer": raw_step.get("transfer"),
            "weather_icon": raw_step.get("weather_icon"),
            "weather_temp": raw_step.get("weather_temp"),
            "category": raw_step.get("category"),
        }

        # Remove None values
        return {k: v for k, v in step.items() if v is not None}

    def _build_summary_step(
        self,
        raw_step: Dict[str, Any],
        step_number: int,
        trip_code: str,
        city: str,
        country: str,
    ) -> Dict[str, Any]:
        """Build the summary step with programmatic summary_stats."""

        # Build summary_stats programmatically
        summary_stats = self._generate_summary_stats()

        step = {
            # ===== REQUIRED FIELDS =====
            "step_number": step_number,
            "day_number": 999,
            "title": raw_step.get("title", "Résumé du voyage"),
            "main_image": self._ensure_step_image(raw_step, step_number, trip_code, city, country),

            # ===== BILINGUAL FIELDS =====
            "title_en": raw_step.get("title_en", "Trip Summary"),
            "subtitle": raw_step.get("subtitle", "Votre voyage en un coup d'œil"),
            "subtitle_en": raw_step.get("subtitle_en", "Your trip at a glance"),

            # ===== SUMMARY STATS (PROGRAMMATIC) =====
            "summary_stats": summary_stats,
        }

        return {k: v for k, v in step.items() if v is not None}

    def _generate_summary_stats(self) -> List[Dict[str, Any]]:
        """
        Génère programmatiquement 4-8 summary_stats pour la step récapitulative.

        Types disponibles: days, budget, weather, style, cities, people, activities, custom
        """
        stats = []

        # STAT 1: Days
        total_days = self._build_total_days()
        stats.append({
            "type": "days",
            "value": str(total_days),
            "label": "Jours",
            "label_en": "Days",
        })

        # STAT 2: Budget
        total_price = self._build_total_price()
        if total_price:
            currency = self._build_currency()
            stats.append({
                "type": "budget",
                "value": f"{int(total_price)}",
                "label": f"Budget ({currency})",
                "label_en": f"Budget ({currency})",
            })

        # STAT 3: Weather
        weather_temp = self._build_weather_temp()
        if weather_temp:
            stats.append({
                "type": "weather",
                "value": str(weather_temp),
                "label": "Température",
                "label_en": "Temperature",
            })

        # STAT 4: Style
        ambiance = self.questionnaire.get("ambiance_voyage")
        if ambiance:
            ambiance_labels = {
                "relaxation": ("Détente", "Relaxation"),
                "adventure": ("Aventure", "Adventure"),
                "culture": ("Culture", "Culture"),
                "nature": ("Nature", "Nature"),
            }
            fr_label, en_label = ambiance_labels.get(ambiance, (ambiance.title(), ambiance.title()))
            stats.append({
                "type": "style",
                "value": fr_label,
                "label": "Style",
                "label_en": "Style",
            })

        # STAT 5: People
        nombre_voyageurs = self.questionnaire.get("nombre_voyageurs")
        if nombre_voyageurs:
            stats.append({
                "type": "people",
                "value": str(nombre_voyageurs),
                "label": "Voyageurs",
                "label_en": "Travelers",
            })

        # STAT 6: Activities count
        steps = self.itinerary_plan.get("steps", [])
        activities_count = len([s for s in steps if s.get("day_number", 999) != 999])
        if activities_count > 0:
            stats.append({
                "type": "activities",
                "value": str(activities_count),
                "label": "Activités",
                "label_en": "Activities",
            })

        # STAT 7: Cities
        destination = self._build_destination()
        city = destination.split(',')[0].strip()
        stats.append({
            "type": "cities",
            "value": "1",
            "label": city,
            "label_en": city,
        })

        # STAT 8: Flight type (if available)
        flight_type = self._build_flight_type()
        if flight_type:
            type_labels = {
                "direct": ("Direct", "Direct"),
                "escale": ("Escale", "Layover"),
                "1 escale": ("1 Escale", "1 Layover"),
            }
            fr_label, en_label = type_labels.get(flight_type, (flight_type, flight_type))
            stats.append({
                "type": "custom",
                "value": fr_label,
                "label": "Vol",
                "label_en": "Flight",
            })

        logger.info(f"📊 Generated {len(stats)} summary stats programmatically")
        return stats[:8]  # Max 8 stats

    # =========================================================================
    # IMAGE GUARANTEE METHODS
    # =========================================================================

    def _ensure_step_image(
        self,
        raw_step: Dict[str, Any],
        step_number: int,
        trip_code: str,
        city: str,
        country: str,
    ) -> str:
        """
        GARANTIT qu'une step a une image Supabase.

        Stratégie 3-niveaux:
        1. Chercher dans raw_step (main_image, image)
        2. Appeler images.background() directement via MCP
        3. Fallback Unsplash
        """

        # Level 1: Try from raw_step
        image_candidates = [
            raw_step.get("main_image"),
            raw_step.get("image"),
            raw_step.get("background_image"),
        ]

        for candidate in image_candidates:
            if candidate and "supabase.co" in str(candidate) and "FAILED" not in str(candidate).upper():
                return candidate

        # Level 2: Call MCP tool directly
        logger.warning(f"⚠️ Step {step_number}: No valid image from agent, calling MCP...")

        step_title = raw_step.get("title", f"Activity {step_number}")
        image_url = self._call_mcp_tool(
            "images.background",
            query=step_title,
            city=city,
            country=country,
            trip_code=trip_code,
            step_number=step_number,
        )

        if image_url and "supabase.co" in image_url:
            logger.info(f"✅ Step {step_number}: Image generated via MCP")
            return image_url

        # Level 3: Fallback Unsplash
        logger.warning(f"⚠️ Step {step_number}: MCP failed, using Unsplash fallback")
        return self._build_fallback_image(step_title, "background")

    # =========================================================================
    # GPS GUARANTEE METHODS
    # =========================================================================

    def _ensure_latitude(self, raw_step: Dict[str, Any], city: str, country: str) -> Optional[float]:
        """Ensure latitude is present, call geo.text_to_place if missing."""
        lat = raw_step.get("latitude")
        if lat is not None:
            return float(lat)

        # Try to get GPS from MCP
        gps = self._get_gps_from_mcp(raw_step.get("title", city), city, country)
        return gps.get("latitude") if gps else None

    def _ensure_longitude(self, raw_step: Dict[str, Any], city: str, country: str) -> Optional[float]:
        """Ensure longitude is present, call geo.text_to_place if missing."""
        lon = raw_step.get("longitude")
        if lon is not None:
            return float(lon)

        # Try to get GPS from MCP
        gps = self._get_gps_from_mcp(raw_step.get("title", city), city, country)
        return gps.get("longitude") if gps else None

    def _get_gps_from_mcp(
        self,
        place_name: str,
        city: str,
        country: str,
    ) -> Dict[str, Optional[float]]:
        """Get GPS coordinates via geo.text_to_place MCP tool."""
        result = self._call_mcp_tool(
            "geo.text_to_place",
            text=f"{place_name}, {city}, {country}",
        )

        if result and isinstance(result, dict):
            return {
                "latitude": result.get("latitude"),
                "longitude": result.get("longitude"),
            }

        return {"latitude": None, "longitude": None}

    # =========================================================================
    # MCP TOOL DIRECT INVOCATION
    # =========================================================================

    def _call_mcp_tool(self, tool_name: str, **kwargs) -> Optional[Any]:
        """
        Appelle un outil MCP directement (sans passer par l'agent).

        Args:
            tool_name: Name of the MCP tool (e.g., "images.hero", "geo.text_to_place")
            **kwargs: Tool parameters

        Returns:
            Tool result or None if failed
        """
        try:
            # Find the tool in mcp_tools list
            tool = None
            for t in self.mcp_tools:
                if hasattr(t, 'name') and t.name == tool_name:
                    tool = t
                    break

            if not tool:
                logger.warning(f"⚠️ MCP tool '{tool_name}' not found in mcp_tools")
                return None

            # Call the tool directly
            logger.info(f"🔧 Calling MCP tool directly: {tool_name}({kwargs})")

            if hasattr(tool, 'func'):
                result = tool.func(**kwargs)
            elif callable(tool):
                result = tool(**kwargs)
            else:
                logger.warning(f"⚠️ Tool '{tool_name}' is not callable")
                return None

            logger.info(f"✅ MCP tool '{tool_name}' returned: {str(result)[:100]}")
            return result

        except Exception as e:
            logger.error(f"❌ Failed to call MCP tool '{tool_name}': {e}")
            return None

    # =========================================================================
    # FALLBACK METHODS
    # =========================================================================

    def _build_fallback_image(self, query: str, image_type: str = "background") -> str:
        """
        Build fallback Unsplash image URL.

        Args:
            query: Search query for image
            image_type: "hero" or "background"

        Returns:
            Unsplash URL
        """
        clean_query = re.sub(r'[^a-zA-Z0-9\s]', '', query).strip().replace(' ', '%20')

        if image_type == "hero":
            return f"https://source.unsplash.com/1920x1080/?{clean_query},travel,destination"
        else:
            return f"https://source.unsplash.com/800x600/?{clean_query},travel,activity"

    def _extract_price(self, price_value: Any) -> Optional[float]:
        """Extract numeric price from various formats."""
        if price_value is None:
            return None

        if isinstance(price_value, (int, float)):
            return float(price_value)

        # Try to extract number from string
        match = re.search(r'(\d+(?:\.\d+)?)', str(price_value))
        if match:
            return float(match.group(1))

        return None

    # =========================================================================
    # VALIDATION
    # =========================================================================

    def _validate_schema(self, trip_json: Dict[str, Any]) -> None:
        """
        Valide que le JSON respecte le schéma Trip.

        Vérifie:
        - Champs requis présents (code, destination, total_days, steps)
        - Steps ont tous les champs requis (step_number, day_number, title, main_image)
        - Images sont des URLs valides
        - GPS coordinates sont présentes quand possible

        Raises:
            ValueError: Si le JSON ne respecte pas le schéma
        """
        errors = []

        # Check required trip-level fields
        required_fields = ["code", "destination", "total_days", "steps"]
        for field in required_fields:
            if field not in trip_json or trip_json[field] is None:
                errors.append(f"Missing required field: {field}")

        # Check steps
        steps = trip_json.get("steps", [])
        if not steps:
            errors.append("No steps found")

        for idx, step in enumerate(steps, 1):
            step_required = ["step_number", "day_number", "title", "main_image"]
            for field in step_required:
                if field not in step or step[field] is None:
                    errors.append(f"Step {idx}: Missing required field '{field}'")

            # Check image is a valid URL
            main_image = step.get("main_image", "")
            if not main_image or not (main_image.startswith("http")):
                errors.append(f"Step {idx}: Invalid main_image URL")

        if errors:
            error_msg = "\n".join(errors)
            logger.error(f"❌ Schema validation failed:\n{error_msg}")
            raise ValueError(f"Schema validation failed:\n{error_msg}")

        logger.info("✅ Schema validation passed")
