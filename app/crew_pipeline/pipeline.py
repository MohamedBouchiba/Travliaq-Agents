"""Pipeline CrewAI complète (scripts + agents) pour générer le YAML/JSON Trip."""

from __future__ import annotations

import logging
import os
import re
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import yaml
from crewai import Agent, Crew, Process, Task
from crewai import LLM

from app.config import settings
from app.crew_pipeline.logging_config import setup_pipeline_logging
from app.crew_pipeline.mcp_tools import get_mcp_tools
from app.crew_pipeline.scripts import (
    NormalizationError,
    normalize_questionnaire,
    validate_trip_schema,
    calculate_trip_budget,
    calculate_trip_structure,
)
from app.crew_pipeline.scripts.incremental_trip_builder import IncrementalTripBuilder
from app.crew_pipeline.scripts.step_template_generator import StepTemplateGenerator
from app.crew_pipeline.scripts.translation_service import TranslationService
from app.crew_pipeline.scripts.step_validator import StepValidator
from app.crew_pipeline.scripts.post_processor import PostProcessor
from app.services.supabase_service import supabase_service
from app.services.pipeline_tracking import get_tracking_service
from app.services.email_notification import send_trip_summary_email_async

logger = logging.getLogger(__name__)

# Variable globale pour éviter l'initialisation multiple du logging
_logging_initialized = False


class MCPToolsManager:
    """
    Wrapper pour les outils MCP qui expose une méthode call_tool().
    Permet à StepTemplateGenerator d'appeler les outils par nom.
    """

    def __init__(self, tools_list: List[Any]):
        self.tools = {tool.name: tool for tool in tools_list}

    def call_tool(self, tool_name: str, **kwargs) -> Any:
        """
        Appelle un outil MCP par son nom.

        Args:
            tool_name: Nom de l'outil (ex: "geo.place")
            **kwargs: Arguments à passer à l'outil

        Returns:
            Résultat de l'outil (parsé depuis JSON si nécessaire)

        Raises:
            ValueError: Si l'outil n'existe pas
        """
        if tool_name not in self.tools:
            raise ValueError(f"Tool '{tool_name}' not found. Available: {list(self.tools.keys())}")

        tool = self.tools[tool_name]

        # Appeler la méthode _run de BaseTool avec les arguments
        result = tool._run(**kwargs)

        # Si le résultat est une string JSON, la parser
        if isinstance(result, str):
            try:
                parsed_result = json.loads(result)

                # 🆕 Si c'est la nouvelle structure MCP standardisée {success, results, ...}
                # extraire le champ "results"
                if isinstance(parsed_result, dict) and "results" in parsed_result:
                    return parsed_result["results"]

                return parsed_result
            except (json.JSONDecodeError, ValueError):
                # Pas du JSON valide, retourner tel quel
                return result

        # Si le résultat est déjà un dict Python avec la structure standardisée
        if isinstance(result, dict) and "results" in result:
            return result["results"]

        return result


PLACEHOLDER_MARKERS = {"your_key_here", "your_key*here", "changeme"}


def _pick_first_secret(*candidates: str | None) -> str | None:
    """Retourne le premier secret non vide qui n'est pas un placeholder."""

    for candidate in candidates:
        if candidate is None:
            continue

        trimmed = str(candidate).strip()
        lower = trimmed.lower()
        if not trimmed:
            continue

        if any(marker in lower for marker in PLACEHOLDER_MARKERS):
            continue

        return trimmed

    return None


def _build_default_llm() -> LLM:
    """Construit le LLM par défaut en filtrant les placeholders."""

    provider = (os.getenv("LLM_PROVIDER") or getattr(settings, "llm_provider", None) or "openai").lower()
    model = os.getenv("MODEL") or settings.model_name
    temperature = settings.temperature

    if provider.startswith("azure"):
        return LLM(
            model=model,
            api_key=_pick_first_secret(os.getenv("AZURE_OPENAI_API_KEY"), settings.azure_openai_api_key),
            base_url=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
            temperature=temperature,
            timeout=120,
            max_retries=3,
        )

    if provider.startswith("groq"):
        return LLM(
            model=model,
            api_key=_pick_first_secret(os.getenv("GROQ_API_KEY"), settings.groq_api_key),
            temperature=temperature,
            timeout=120,
            max_retries=3,
        )

    return LLM(
        model=model,
        api_key=_pick_first_secret(os.getenv("OPENAI_API_KEY"), settings.openai_api_key),
        temperature=temperature,
        timeout=120,
        max_retries=3,
    )


@dataclass
class CrewPipelineResult:
    """Résultat structuré de la pipeline complète."""
    run_id: str
    status: str
    normalized_trip_request: Dict[str, Any] = field(default_factory=dict)
    tasks_output: List[Dict[str, Any]] = field(default_factory=list)
    raw_output: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "normalized_trip_request": self.normalized_trip_request,
            "tasks_output": self.tasks_output,
            "raw_output": self.raw_output,
        }


@dataclass
class TripIntent:
    """Décision d'orchestration issue du questionnaire utilisateur."""

    destination_locked: bool
    destination_value: Optional[str]
    assist_flights: bool
    assist_accommodation: bool
    assist_activities: bool

    @property
    def should_scout(self) -> bool:
        return not self.destination_locked


class CrewPipeline:
    """
    Orchestrateur complet (scripts + CrewAI) pour construire un trip Travliaq.

    Etapes clés :
    - T0 script : normalisation questionnaire
    - T1 script + agent : persona inference (orchestrée)
    - T2-T4 : analyse persona & trip spec (agents)
    - T5 script : system contract draft
    - T6-T10 : scouting, pricing, activités, budget, décision, gate (agents)
    - T11 scripts : assemblage + validation JSON Schema
    """

    def __init__(
        self,
        *,
        llm: Optional[LLM] = None,
        verbose: Optional[bool] = None,
        output_dir: Optional[Path] = None,
        crew_builder: Optional[Any] = None,
    ) -> None:
        self._llm = llm or _build_default_llm()
        self._verbose = verbose if verbose is not None else settings.verbose
        self._output_dir = Path(output_dir) if output_dir is not None else Path(settings.effective_crew_output_dir)
        self._config_dir = Path(__file__).resolve().parent / "config"
        self._crew_builder = crew_builder or self._build_crew
        self._use_mock_crew = crew_builder is not None

    def _derive_trip_intent(
        self,
        questionnaire: Dict[str, Any],
        normalized_trip_request: Dict[str, Any],
    ) -> TripIntent:
        """Déduit les besoins réels (scouting vs optimisation) à partir des réponses utilisateur."""

        help_with = questionnaire.get("help_with")
        if not help_with and isinstance(normalized_trip_request, dict):
            assist = normalized_trip_request.get("assist_needed") or {}
            if isinstance(assist, dict):
                help_with = [key for key, value in assist.items() if value]

        help_set = {str(item).strip().lower() for item in help_with or [] if item}
        has_explicit_scope = bool(help_set)

        assist_flights = "flights" in help_set if has_explicit_scope else True
        assist_accommodation = "accommodation" in help_set if has_explicit_scope else True
        assist_activities = "activities" in help_set if has_explicit_scope else True

        destination_value = questionnaire.get("destination") or questionnaire.get("destination_precise")
        if not destination_value and isinstance(normalized_trip_request, dict):
            destinations = (
                normalized_trip_request.get("trip_frame", {})
                if isinstance(normalized_trip_request, dict)
                else {}
            )
            if isinstance(destinations, dict):
                primary = None
                for dest in destinations.get("destinations", []) or []:
                    if isinstance(dest, dict) and dest.get("city"):
                        primary = dest.get("city")
                        break
                destination_value = primary or destination_value

        has_destination = str(questionnaire.get("has_destination") or "").lower() == "yes"
        destination_locked = bool(destination_value) and has_destination

        return TripIntent(
            destination_locked=destination_locked,
            destination_value=destination_value,
            assist_flights=assist_flights,
            assist_accommodation=assist_accommodation,
            assist_activities=assist_activities,
        )

    def run(
        self,
        *,
        questionnaire_data: Dict[str, Any],
        persona_inference: Dict[str, Any],
        payload_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Exécute la pipeline complète (scripts + agents)."""

        # Initialiser le logging une seule fois au début de l'exécution
        global _logging_initialized
        if not _logging_initialized:
            setup_pipeline_logging(level=logging.INFO, console_output=True)
            _logging_initialized = True

        run_id = self._generate_run_id(questionnaire_data)
        questionnaire_id = self._extract_id(questionnaire_data)
        logger.info(f"🚀 Lancement Pipeline CrewAI (Run ID: {run_id}, Questionnaire: {questionnaire_id[:8] if questionnaire_id else 'N/A'}...)")

        # 📊 Marquer le début de la pipeline
        tracking_service = get_tracking_service()
        if questionnaire_id:
            # Calculer le persona dès le début (pour email personnalisé)
            persona_text = persona_inference.get("persona_label", "") if persona_inference else ""
            tracking_service.mark_pipeline_running(
                questionnaire_id=questionnaire_id,
                run_id=run_id,
                persona=persona_text,
            )

        # ✅ Création anticipée du dossier de run en mode développement
        should_save = settings.environment.lower() == "development"
        run_dir = self._output_dir / run_id
        if should_save:
            run_dir.mkdir(parents=True, exist_ok=True)
            # Sauvegarde des entrées brutes pour faciliter le debug
            self._write_yaml(
                run_dir / "_INPUT_payload.yaml",
                {
                    "questionnaire": questionnaire_data,
                    "persona_inference": persona_inference,
                    "metadata": payload_metadata or {},
                },
            )

        # Mode simplifié pour les tests unitaires : on injecte un Crew factice via crew_builder
        if self._use_mock_crew:
            return self._run_with_mocked_crew(
                questionnaire_data, persona_inference, run_id, run_dir if should_save else None
            )

        # 0. Normalisation déterministe (script)
        try:
            normalization = normalize_questionnaire(questionnaire_data)
        except NormalizationError as exc:
            # 📊 Marquer l'échec de normalisation
            if questionnaire_id:
                tracking_service.mark_pipeline_failed(
                    questionnaire_id=questionnaire_id,
                    error=f"Normalization failed: {str(exc)}",
                )
                logger.error(f"❌ Pipeline FAILED (normalization) for questionnaire {questionnaire_id[:8]}...: {exc}")

            failed_payload = {
                "run_id": run_id,
                "status": "failed_normalization",
                "error": str(exc),
                "metadata": {"questionnaire_id": self._extract_id(questionnaire_data)},
            }
            if should_save:
                self._write_yaml(run_dir / "_FAILED_normalization.yaml", failed_payload)
            return failed_payload

        normalized_questionnaire = normalization.get("questionnaire", {})

        if should_save:
            phase0_dir = run_dir / "PHASE0_NORMALIZATION"
            phase0_dir.mkdir(parents=True, exist_ok=True)
            self._write_yaml(
                phase0_dir / "normalized_questionnaire.yaml",
                normalization,
            )

        # Conversion YAML pour les prompts agents
        questionnaire_yaml = yaml.dump(normalized_questionnaire, allow_unicode=True, sort_keys=False)
        persona_yaml = yaml.dump(persona_inference, allow_unicode=True, sort_keys=False)

        # 1. Chargement de la configuration
        agents_config = self._load_yaml_config("agents.yaml")
        if "agents" in agents_config:
            agents_config = agents_config["agents"]
        tasks_config = self._load_yaml_config("tasks.yaml")
        if "tasks" in tasks_config:
            tasks_config = tasks_config["tasks"]

        # 2. Outils MCP
        mcp_tools: List[Any] = []
        mcp_manager: Optional[MCPToolsManager] = None
        if settings.mcp_server_url:
            try:
                mcp_tools = get_mcp_tools(settings.mcp_server_url)
                mcp_manager = MCPToolsManager(mcp_tools)
                logger.info(f"✅ {len(mcp_tools)} outils MCP chargés.")
            except Exception as e:
                logger.warning(f"⚠️ Erreur chargement MCP: {e}")

        # 3. Agents nécessaires (architecture optimisée - 5 agents LLM + 3 scripts Python)
        #
        # ✅ AGENTS LLM (requis pour créativité et contexte):
        context_builder = self._create_agent("trip_context_builder", agents_config["trip_context_builder"], tools=[])
        strategist = self._create_agent("destination_strategist", agents_config["destination_strategist"], tools=mcp_tools)
        flight_specialist = self._create_agent("flights_specialist", agents_config["flights_specialist"], tools=mcp_tools)
        accommodation_specialist = self._create_agent("accommodation_specialist", agents_config["accommodation_specialist"], tools=mcp_tools)
        itinerary_designer = self._create_agent("itinerary_designer", agents_config["itinerary_designer"], tools=mcp_tools)

        # 🚀 REMPLACÉS PAR SCRIPTS PYTHON (10x plus rapide, 100x moins cher, 100% fiable):
        # trip_structure_planner → calculate_trip_structure() script
        # budget_calculator → calculate_trip_budget() script
        # final_assembler → IncrementalTripBuilder (déjà fait tout le travail)

        # 4. Phase 1 - Context & Strategy
        task1 = Task(name="trip_context_building", agent=context_builder, **tasks_config["trip_context_building"])
        task2 = Task(name="destination_strategy", agent=strategist, context=[task1], **tasks_config["destination_strategy"])

        crew_phase1 = self._crew_builder(
            agents=[context_builder, strategist],
            tasks=[task1, task2],
            verbose=self._verbose,
            process=Process.sequential,
        )

        inputs_phase1 = {
            "questionnaire": questionnaire_yaml,
            "persona_context": persona_yaml,
            "current_year": datetime.now().year,
        }

        output_phase1 = crew_phase1.kickoff(inputs=inputs_phase1)
        tasks_phase1, parsed_phase1 = self._collect_tasks_output(output_phase1, should_save, run_dir, phase_label="PHASE1_CONTEXT")

        # Extraire trip_context et destination_choice
        trip_context = parsed_phase1.get("trip_context_building", {}).get("trip_context", {})
        destination_strategy = parsed_phase1.get("destination_strategy", {})

        # 🔧 FIX: L'agent peut mettre les données directement dans destination_strategy OU dans destination_choice
        destination_choice = destination_strategy.get("destination_choice", destination_strategy)

        # 🆕 INITIALIZATION: Créer le IncrementalTripBuilder dès qu'on a la destination
        logger.info("🏗️ Initialisation du IncrementalTripBuilder...")
        builder = IncrementalTripBuilder(questionnaire=normalized_questionnaire)

        # 🔧 FIX: Extraction robuste de la destination (plusieurs noms de champs possibles)
        destination = (
            destination_choice.get("destination") or
            destination_choice.get("destination_city") or
            destination_choice.get("destination_name") or
            destination_choice.get("city") or
            normalized_questionnaire.get("destination") or
            "Unknown Destination"
        )

        destination_country = (
            destination_choice.get("country") or
            destination_choice.get("destination_country") or
            normalized_questionnaire.get("country") or
            ""
        )

        destination_en = destination_choice.get("destination_en") or destination

        # 🔧 DEBUG: Logger la destination extraite
        logger.info(f"📍 Destination extraite: {destination}, Country: {destination_country}")
        logger.debug(f"🔍 destination_choice keys: {list(destination_choice.keys())}")

        # Extraire la date de départ
        start_date = normalized_questionnaire.get("date_depart") or \
                    normalized_questionnaire.get("date_depart_approximative") or \
                    datetime.now().strftime("%Y-%m-%d")

        # Extraire le rythme
        rhythm = normalized_questionnaire.get("rythme", "balanced")

        # Initialiser la structure JSON vide
        builder.initialize_structure(
            destination=destination,
            destination_en=destination_en,
            start_date=start_date,
            rhythm=rhythm,
            mcp_tools=mcp_manager if mcp_manager else mcp_tools,
        )

        logger.info(f"✅ Structure JSON initialisée: {builder.trip_json['code']}")  # 🔧 FIX: Accès direct

        # Dériver l'intent depuis trip_context (plus simple que normalized_trip_request)
        trip_intent = self._derive_trip_intent(normalized_questionnaire, trip_context)

        # 5. Phase 2 - Research (conditionnelle selon help_with)
        phase2_tasks: List[Task] = []
        phase2_agents: List[Agent] = []

        # Convertir outputs en YAML pour prompts
        trip_context_yaml = yaml.dump(trip_context, allow_unicode=True, sort_keys=False)
        destination_choice_yaml = yaml.dump(destination_choice, allow_unicode=True, sort_keys=False)

        # 🆕 Ajouter l'état courant du trip JSON (pour que les agents voient la structure)
        current_trip_json_yaml = builder.get_current_state_yaml()

        # Extraire dates validées depuis trip_context
        dates_info = trip_context.get("dates", {}) or {}
        departure_window = dates_info.get("departure_window") or {}
        return_window = dates_info.get("return_window") or {}
        departure_dates = dates_info.get("departure_date") or departure_window.get("start") or "Non spécifiée"
        return_dates = dates_info.get("return_date") or return_window.get("end") or "Non spécifiée"

        inputs_phase2 = {
            "trip_context": trip_context_yaml,
            "destination_choice": destination_choice_yaml,
            "current_trip_json": current_trip_json_yaml,  # 🆕 NOUVEAU
            "current_year": datetime.now().year,
            "validated_departure_dates": departure_dates,
            "validated_return_dates": return_dates,
        }

        # 🆕 STEP 1: Générer plan de structure ET templates AVANT Phase 2
        trip_structure_plan = {}
        step_templates_yaml = None
        tasks_structure = []

        if trip_intent.assist_activities:
            logger.info("📋 Step 1/3: Calculating trip structure with SCRIPT (no LLM)...")

            # 🚀 OPTIMIZATION: Utiliser le script au lieu de l'agent LLM
            # Avantages: 10x plus rapide, 100x moins cher, 100% fiable
            trip_structure_plan = calculate_trip_structure(
                questionnaire=normalized_questionnaire,
                destination=destination,
                destination_country=destination_country or "",
                total_days=builder.trip_json.get("total_days", 7),
            )

            logger.info(f"✅ Trip structure calculated by script: {trip_structure_plan.get('total_steps_planned', 0)} steps")

            # Sauvegarder le plan dans les outputs (pour traçabilité)
            if should_save:
                plan_path = run_dir / "_trip_structure_plan.yaml"
                with open(plan_path, "w", encoding="utf-8") as f:
                    yaml.dump({"trip_structure_plan": trip_structure_plan}, f, allow_unicode=True, sort_keys=False)
                logger.info(f"💾 Trip structure plan saved to {plan_path}")

            # 🆕 Ajuster le nombre de steps dans le builder selon le plan
            if trip_structure_plan:
                planned_total_days = trip_structure_plan.get("total_days")
                planned_total_steps = trip_structure_plan.get("total_steps_planned")

                if planned_total_days and planned_total_steps:
                    current_steps = [s for s in builder.trip_json.get("steps", []) if not s.get("is_summary")]
                    current_count = len(current_steps)

                    if planned_total_steps != current_count:
                        logger.warning(
                            f"⚠️ Step count mismatch: builder has {current_count} steps, "
                            f"plan requires {planned_total_steps} steps. Adjusting..."
                        )

                        # Mettre à jour total_days
                        builder.trip_json["total_days"] = planned_total_days

                        # Ajuster les steps
                        if planned_total_steps > current_count:
                            # Ajouter des steps manquantes
                            summary_step = None
                            if builder.trip_json["steps"] and builder.trip_json["steps"][-1].get("is_summary"):
                                summary_step = builder.trip_json["steps"].pop()

                            # Créer un mapping step_number -> day_number depuis daily_distribution
                            step_to_day = {}
                            daily_dist = trip_structure_plan.get("daily_distribution", [])
                            step_counter = 1
                            for day_info in daily_dist:
                                day_num = day_info.get("day", 1)
                                steps_count = day_info.get("steps_count", 1)
                                for _ in range(steps_count):
                                    step_to_day[step_counter] = day_num
                                    step_counter += 1

                            for i in range(current_count + 1, planned_total_steps + 1):
                                day_number = step_to_day.get(i, ((i - 1) // 3) + 1)  # Fallback si pas trouvé
                                builder.trip_json["steps"].append({
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

                            # Remettre le summary à la fin
                            if summary_step:
                                builder.trip_json["steps"].append(summary_step)

                            # 🆕 PERFORMANCE: Rebuild cache après ajout de steps
                            builder._rebuild_steps_cache()

                            logger.info(f"✅ Added {planned_total_steps - current_count} steps to match plan")
                        elif planned_total_steps < current_count:
                            # Retirer des steps en trop (garder summary)
                            summary_step = None
                            if builder.trip_json["steps"] and builder.trip_json["steps"][-1].get("is_summary"):
                                summary_step = builder.trip_json["steps"].pop()

                            builder.trip_json["steps"] = builder.trip_json["steps"][:planned_total_steps]

                            if summary_step:
                                builder.trip_json["steps"].append(summary_step)

                            # 🆕 PERFORMANCE: Rebuild cache après retrait de steps
                            builder._rebuild_steps_cache()

                            logger.info(f"✅ Removed {current_count - planned_total_steps} steps to match plan")

            # 🆕 STEP 2: Générer templates MAINTENANT (avant Phase 2)
            if trip_structure_plan and trip_structure_plan.get("daily_distribution"):
                logger.info("🏗️ Step 2/3: Generating step templates with GPS and images...")

                try:
                    # Créer un manager pour les outils MCP
                    mcp_manager = MCPToolsManager(mcp_tools)
                    step_template_generator = StepTemplateGenerator(mcp_tools=mcp_manager)
                    step_templates = step_template_generator.generate_templates(
                        trip_structure_plan=trip_structure_plan,
                        destination=destination,
                        destination_country=destination_country or "",
                        trip_code=builder.trip_json["code"],
                    )

                    logger.info(f"✅ {len(step_templates)} step templates generated with GPS and images")

                    # 🆕 Ajuster le builder si le nombre de templates > nombre de steps
                    activity_templates = [t for t in step_templates if not t.get("is_summary")]
                    max_step_num = max([t.get("step_number", 0) for t in activity_templates]) if activity_templates else 0

                    if max_step_num > 0:
                        current_steps = [s for s in builder.trip_json.get("steps", []) if not s.get("is_summary")]
                        current_max = len(current_steps)

                        if max_step_num > current_max:
                            logger.warning(
                                f"⚠️ Templates require {max_step_num} steps, but builder has {current_max}. "
                                f"Adding {max_step_num - current_max} steps..."
                            )

                            # Retirer le summary temporairement
                            summary_step = None
                            if builder.trip_json["steps"] and builder.trip_json["steps"][-1].get("is_summary"):
                                summary_step = builder.trip_json["steps"].pop()

                            # Créer mapping day_number depuis daily_distribution
                            step_to_day = {}
                            daily_dist = trip_structure_plan.get("daily_distribution", [])
                            step_counter = 1
                            for day_info in daily_dist:
                                day_num = day_info.get("day", 1)
                                steps_count = day_info.get("steps_count", 1)
                                for _ in range(steps_count):
                                    step_to_day[step_counter] = day_num
                                    step_counter += 1

                            # Ajouter les steps manquantes
                            for i in range(current_max + 1, max_step_num + 1):
                                day_number = step_to_day.get(i, ((i - 1) // 3) + 1)
                                builder.trip_json["steps"].append({
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

                            # Remettre le summary
                            if summary_step:
                                builder.trip_json["steps"].append(summary_step)

                            # 🆕 PERFORMANCE: Rebuild cache après ajout de steps
                            builder._rebuild_steps_cache()

                            logger.info(f"✅ Added {max_step_num - current_max} steps to match templates")

                    # Enrichir builder avec templates
                    for template in step_templates:
                        if not template.get("is_summary"):
                            step_num = template.get("step_number")
                            if step_num:
                                builder.set_step_gps(
                                    step_number=step_num,
                                    latitude=template.get("latitude", 0),
                                    longitude=template.get("longitude", 0),
                                )
                                if template.get("main_image"):
                                    builder.set_step_image(
                                        step_number=step_num,
                                        image_url=template.get("main_image"),
                                    )
                                if template.get("step_type"):
                                    builder.set_step_type(
                                        step_number=step_num,
                                        step_type=template.get("step_type"),
                                    )

                    logger.info("✅ Builder enriched with GPS and images from templates")

                    # Mettre à jour current_trip_json pour Phase 2
                    current_trip_json_yaml = builder.get_current_state_yaml()
                    inputs_phase2["current_trip_json"] = current_trip_json_yaml

                    # Ajouter step_templates aux inputs (pour que l'agent les voie)
                    step_templates_yaml = yaml.dump(step_templates, allow_unicode=True, sort_keys=False)
                    inputs_phase2["step_templates"] = step_templates_yaml

                    logger.info("✅ inputs_phase2 updated with enriched trip JSON and templates")

                except Exception as e:
                    logger.error(f"❌ StepTemplateGenerator failed: {e}")
                    logger.warning("⚠️ Continuing without templates, Agent 6 will generate from scratch")
            else:
                logger.warning("⚠️ No trip_structure_plan found, skipping template generation")

        # 🆕 STEP 3: Construire Phase 2 avec les autres tâches (Flights, Accommodation, Itinerary)
        logger.info("🚀 Step 3/3: Executing Phase 2 (Flights, Accommodation, Itinerary Design)...")

        # 🚀 OPTIMIZATION: Exécution parallèle des agents Phase 2
        parsed_phase2 = {}
        tasks_phase2 = []

        # Ajouter les résultats de plan_trip_structure déjà obtenus
        if trip_intent.assist_activities and trip_structure_plan:
            parsed_phase2["plan_trip_structure"] = {"structural_plan": trip_structure_plan}

        # Créer les crews individuels pour exécution parallèle
        parallel_crews = []

        if trip_intent.assist_flights:
            flight_task = Task(name="flights_research", agent=flight_specialist, **tasks_config["flights_research"])
            flight_crew = self._crew_builder(
                agents=[flight_specialist],
                tasks=[flight_task],
                verbose=self._verbose,
                process=Process.sequential,
            )
            parallel_crews.append(("flights_research", flight_crew))

        if trip_intent.assist_accommodation:
            lodging_task = Task(name="accommodation_research", agent=accommodation_specialist, **tasks_config["accommodation_research"])
            accommodation_crew = self._crew_builder(
                agents=[accommodation_specialist],
                tasks=[lodging_task],
                verbose=self._verbose,
                process=Process.sequential,
            )
            parallel_crews.append(("accommodation_research", accommodation_crew))

        if trip_intent.assist_activities and step_templates_yaml:
            itinerary_task = Task(
                name="itinerary_design",
                agent=itinerary_designer,
                **tasks_config["itinerary_design"]
            )
            itinerary_crew = self._crew_builder(
                agents=[itinerary_designer],
                tasks=[itinerary_task],
                verbose=self._verbose,
                process=Process.sequential,
            )
            parallel_crews.append(("itinerary_design", itinerary_crew))

        # Lancer Phase 2 en parallèle si au moins un service demandé
        if parallel_crews:
            logger.info(f"⚡ Launching {len(parallel_crews)} crews in parallel...")

            # Exécuter tous les crews en parallèle
            with ThreadPoolExecutor(max_workers=len(parallel_crews)) as executor:
                # Soumettre tous les crews
                future_to_crew = {
                    executor.submit(crew.kickoff, inputs_phase2): crew_name
                    for crew_name, crew in parallel_crews
                }

                # Collecter les résultats au fur et à mesure
                for future in as_completed(future_to_crew):
                    crew_name = future_to_crew[future]
                    try:
                        output = future.result()
                        tasks_new, parsed_new = self._collect_tasks_output(
                            output, should_save, run_dir, phase_label=f"PHASE2_{crew_name.upper()}"
                        )
                        tasks_phase2.extend(tasks_new)
                        parsed_phase2.update(parsed_new)
                        logger.info(f"✅ {crew_name} completed")
                    except Exception as e:
                        logger.error(f"❌ {crew_name} failed: {e}")
                        raise

            # Fusionner avec les résultats de structure déjà obtenus
            if trip_intent.assist_activities:
                tasks_phase2 = tasks_structure + tasks_phase2

            # 🆕 ENRICHISSEMENT: Mettre à jour le builder avec les résultats de PHASE2
            logger.info("🔧 Enrichissement du trip JSON avec les résultats de PHASE2...")
            self._enrich_builder_from_phase2(builder, parsed_phase2, mcp_manager)

            # 🆕 SCRIPT 2: Traduire contenu FR → EN
            if trip_intent.assist_activities:
                logger.info("🌍 Translating itinerary content FR → EN...")
                
                # Récupérer steps depuis builder
                current_trip = builder.trip_json
                steps_to_translate = current_trip.get("steps", [])
                
                if steps_to_translate:
                    try:
                        # Initialiser service de traduction
                        translation_service = TranslationService(llm=self._llm)
                        
                        # Traduire toutes les steps
                        translated_steps = translation_service.translate_steps(steps_to_translate)
                        
                        # Mettre à jour le builder avec steps traduites
                        for step in translated_steps:
                            step_num = step.get("step_number")
                            
                            if step_num and step_num != 99:  # Skip summary
                                builder.set_step_title(
                                    step_number=step_num,
                                    title=step.get("title", ""),
                                    title_en=step.get("title_en", ""),
                                    subtitle=step.get("subtitle", ""),
                                    subtitle_en=step.get("subtitle_en", ""),
                                )
                                
                                builder.set_step_content(
                                    step_number=step_num,
                                    why=step.get("why", ""),
                                    why_en=step.get("why_en", ""),
                                    tips=step.get("tips", ""),
                                    tips_en=step.get("tips_en", ""),
                                    transfer=step.get("transfer", ""),
                                    transfer_en=step.get("transfer_en", ""),
                                    suggestion=step.get("suggestion", ""),
                                    suggestion_en=step.get("suggestion_en", ""),
                                )
                                
                                # Météo si disponible
                                if step.get("weather_description_en"):
                                    builder.set_step_weather(
                                        step_number=step_num,
                                        icon=step.get("weather_icon", ""),
                                        temp=step.get("weather_temp", ""),
                                        description=step.get("weather_description", ""),
                                        description_en=step.get("weather_description_en", ""),
                                    )
                        
                        logger.info(f"✅ {len(translated_steps)} steps translated FR → EN")
                        
                    except Exception as e:
                        logger.error(f"❌ TranslationService failed: {e}")
                        logger.warning("⚠️ Continuing without translations")
                else:
                    logger.warning("⚠️ No steps found for translation")

            # 🆕 SCRIPT 3: Valider et corriger steps automatiquement
            validation_report = None  # Track validation results for later reporting
            if trip_intent.assist_activities:
                logger.info("🔍 Validating all steps...")

                # Récupérer steps depuis builder
                current_trip = builder.trip_json
                steps_to_validate = current_trip.get("steps", [])
                
                if steps_to_validate:
                    try:
                        # Initialiser validateur
                        validator = StepValidator(mcp_tools=mcp_manager if mcp_manager else mcp_tools, llm=self._llm)
                        
                        # Valider et auto-fix
                        validated_steps, validation_report = validator.validate_all_steps(
                            steps=steps_to_validate,
                            auto_fix=True,  # Auto-correction activée
                            destination=destination,
                            destination_country=destination_country or "",
                            trip_code=current_trip.get("code", ""),
                        )
                        
                        # Logger rapport
                        logger.info(
                            f"✅ Validation: {validation_report['valid_steps']}/{validation_report['total_steps']} valid, "
                            f"{validation_report['fixes_applied']} auto-fixed"
                        )
                        
                        if validation_report["invalid_steps"] > 0:
                            logger.warning(f"⚠️ {validation_report['invalid_steps']} steps still invalid after auto-fix")
                            for detail in validation_report.get("details", []):
                                logger.warning(f"  Step {detail.get('step_number')}: {detail.get('errors_after', detail.get('errors', []))}")
                        
                        # Remplacer steps dans builder par versions validées
                        builder.trip_json["steps"] = validated_steps

                        # 🆕 PERFORMANCE: Rebuild cache après validation/modification de steps
                        builder._rebuild_steps_cache()
                        
                        logger.info("✅ Steps validation complete, builder updated")
                        
                    except Exception as e:
                        logger.error(f"❌ StepValidator failed: {e}")
                        logger.warning("⚠️ Continuing without validation")
                else:
                    logger.warning("⚠️ No steps to validate")

        # 6. Phase 3 - Budget (script) + Assembly (agent)

        # 🚀 OPTIMIZATION: Budget calculation via script (no LLM needed)
        logger.info("💰 Calculating budget with deterministic script...")
        budget_result = calculate_trip_budget(
            parsed_phase2=parsed_phase2,
            trip_context=trip_context,
        )

        # Save budget result
        if should_save:
            budget_path = run_dir / "budget_calculation.json"
            with open(budget_path, "w", encoding="utf-8") as f:
                json.dump(budget_result, f, indent=2, ensure_ascii=False)
            logger.info(f"💾 Budget saved to {budget_path}")

        # 🚀 OPTIMIZATION: Final assembly is now 100% script-based (no LLM needed)
        # Le builder a déjà toutes les données via _enrich_builder_from_phase2()
        # Il ne reste qu'à ajouter le budget calculé
        logger.info("🔧 Enriching trip JSON with budget (script-based)...")

        # Simuler parsed_phase3 pour compatibilité avec _enrich_builder_from_phase3
        parsed_phase3 = {"budget_calculation": budget_result}

        # Mettre à jour le builder avec le budget
        self._enrich_builder_from_phase3(builder, parsed_phase3)

        # 🚀 Phase 3 tasks: vide car 100% script-based (plus d'agents LLM)
        tasks_phase3 = []

        # 🆕 Mettre à jour les summary stats
        builder.update_summary_stats()

        # 🆕 Récupérer le JSON final depuis le builder
        trip_payload = builder.get_json()

        # 🆕 Log du rapport de complétude pour debug
        completeness = builder.get_completeness_report()
        logger.info(f"📊 Rapport de complétude du trip:")
        logger.info(f"   - Complétude trip: {completeness['trip_completeness']}")
        logger.info(f"   - Steps avec titre: {completeness['steps_with_title']}")
        logger.info(f"   - Steps avec image: {completeness['steps_with_image']}")
        logger.info(f"   - Steps avec GPS: {completeness['steps_with_gps']}")
        if completeness['missing_critical']:
            logger.warning(f"   - ⚠️ Champs critiques manquants: {completeness['missing_critical']}")

        # Warn if validation found invalid steps
        if validation_report and validation_report.get("invalid_steps", 0) > 0:
            logger.warning(
                f"   - ⚠️ Content validation: {validation_report['invalid_steps']}/{validation_report['total_steps']} steps "
                f"have validation errors (see warnings above for details)"
            )
            logger.warning("   - ⚠️ Despite 100% structure completeness, content quality may be insufficient")

        # 🛡️ SAFETY 1: Remove duplicate summary steps (keep only step 99)
        if isinstance(trip_payload, dict) and "steps" in trip_payload:
            summary_steps = [s for s in trip_payload["steps"] if s.get("is_summary")]

            if len(summary_steps) > 1:
                logger.warning(f"⚠️ Detected {len(summary_steps)} summary steps - removing duplicates (keeping step 99)")

                # Find step 99
                step_99 = next((s for s in summary_steps if s.get("step_number") == 99), None)

                if not step_99:
                    # No step 99? Keep the first summary and change its step_number to 99
                    step_99 = summary_steps[0]
                    step_99["step_number"] = 99
                    step_99["day_number"] = 0
                    logger.warning("⚠️ No step 99 found, converted first summary step to step 99")

                # Merge data from other summary steps into step 99 if they have better data
                for other_summary in summary_steps:
                    if other_summary.get("step_number") == 99:
                        continue

                    # Merge non-empty fields into step 99
                    for field in ["title", "subtitle", "main_image", "summary_stats"]:
                        if not step_99.get(field) and other_summary.get(field):
                            step_99[field] = other_summary[field]
                            logger.debug(f"  Merged {field} from duplicate summary step {other_summary.get('step_number')}")

                # Remove all summary steps except step 99
                trip_payload["steps"] = [
                    s for s in trip_payload["steps"]
                    if not s.get("is_summary") or s.get("step_number") == 99
                ]

                logger.info(f"✅ Removed {len(summary_steps) - 1} duplicate summary steps, kept step 99")

        # 🛡️ SAFETY 2: Ensure all steps have non-empty titles (especially summary step)
        if isinstance(trip_payload, dict) and "steps" in trip_payload:
            for step in trip_payload["steps"]:
                # Fix empty titles in summary steps
                if step.get("is_summary") and (not step.get("title") or step.get("title") == ""):
                    step["title"] = "Résumé du voyage"
                    step["title_en"] = "Trip Summary"
                    logger.warning(f"⚠️ Fixed empty title in summary step (step_number: {step.get('step_number')})")

                # Fix empty titles in regular steps
                elif not step.get("is_summary") and (not step.get("title") or step.get("title") == ""):
                    day_num = step.get("day_number", "?")
                    step["title"] = f"Activité Jour {day_num}"
                    step["title_en"] = f"Activity Day {day_num}"
                    logger.warning(
                        f"⚠️ Fixed empty title in regular step {step.get('step_number')} (Day {day_num})"
                    )

        # 🔧 FIX: Nettoyer les champs techniques avant validation
        if isinstance(trip_payload, dict) and "steps" in trip_payload:
            for step in trip_payload["steps"]:
                # Retirer champs techniques ajoutés par scripts (non dans schéma)
                step.pop("_enriched", None)  # Ajouté par PostProcessingEnricher
                step.pop("_validated", None)  # Potentiellement ajouté par StepValidator
                step.pop("_template", None)  # Potentiellement ajouté par StepTemplateGenerator

        # Validation Schema
        is_valid, schema_error = False, "No trip payload generated"

        # 🔧 FIX: trip_payload est maintenant l'objet trip direct (plus de wrapper "trip")
        if isinstance(trip_payload, dict) and "destination" in trip_payload:
            is_valid, schema_error = validate_trip_schema(trip_payload)
        elif "error" in trip_payload:
            schema_error = trip_payload.get("error_message", "Agent returned error")

        if should_save:
            validation_dir = run_dir / "PHASE3_VALIDATION"
            validation_dir.mkdir(parents=True, exist_ok=True)
            self._write_yaml(validation_dir / "trip_payload.yaml", trip_payload)
            self._write_yaml(
                validation_dir / "schema_validation.yaml",
                {"schema_valid": is_valid, "schema_error": schema_error},
            )

        persistence = {
            "saved": False,
            "table": settings.trip_recommendations_table,
            "schema_valid": is_valid,
            "inserted_via_function": False,
            "supabase_trip_id": None,
        }

        trip_core = trip_payload  # 🔧 FIX: trip_core EST trip_payload
        trip_code = trip_core.get("code") if trip_core and isinstance(trip_core, dict) else None

        if trip_core and isinstance(trip_core, dict) and "destination" in trip_core:
            try:
                if is_valid:
                    # 🛡️ SAFETY CHECK: Valider et réparer les données critiques avant sauvegarde
                    self._validate_and_fix_trip_data(builder)
                    trip_core = builder.get_json() # Refresh after fix

                    # 1️⃣ Insérer le trip dans la table trips
                    trip_id = supabase_service.insert_trip_from_json(trip_core)
                    persistence["inserted_via_function"] = bool(trip_id)
                    persistence["supabase_trip_id"] = trip_id
                    logger.info(f"✅ Trip inserted in trips table: {trip_id}")

                    # 2️⃣ Créer le résumé dans trip_summaries (AVEC TOUTES LES DONNÉES)
                    logger.info(f"📊 Creating trip summary for questionnaire {questionnaire_id[:8]}...")
                    summary_id = supabase_service.save_trip_summary(
                        questionnaire_id=questionnaire_id,
                        questionnaire_data=questionnaire_data,
                        persona_inference=persona_inference,
                        persona_analysis={},  # Vide si pas disponible
                        trip_json=trip_core,
                        run_id=run_id,
                        pipeline_status="SUCCESS",
                    )

                    persistence["trip_summary_id"] = summary_id

                    if summary_id:
                        logger.info(f"✅ Trip summary created in trip_summaries: {summary_id}")
                        logger.info(f"   → trip_code: {trip_code}")
                        logger.info(f"   → destination: {trip_core.get('destination')}")
                        logger.info(f"   → questionnaire_id: {questionnaire_id[:8]}...")

                        # 3️⃣ Envoyer l'email avec l'ID du summary (PAS questionnaire_id !)
                        logger.info(f"📧 Sending email notification with summary_id: {summary_id[:8]}...")
                        send_trip_summary_email_async(summary_id)
                        logger.info(f"✅ Email notification sent successfully!")
                    else:
                        logger.warning(f"⚠️ Trip summary creation failed, email NOT sent")

                    # 4️⃣ Tracking (optionnel, déjà fait dans save_trip_summary)
                    if questionnaire_id and trip_code:
                        tracking_service.mark_pipeline_success(
                            questionnaire_id=questionnaire_id,
                            trip_code=trip_code,
                            persona=persona_text if 'persona_text' in locals() else None,
                        )

                # 5️⃣ Sauvegarde dans trip_recommendations (table legacy)
                persistence["saved"] = supabase_service.save_trip_recommendation(
                    run_id=run_id,
                    questionnaire_id=self._extract_id(normalized_questionnaire),
                    trip_json=trip_core,
                    status="success" if is_valid else "failed_validation",
                    schema_valid=is_valid,
                    metadata={
                        "task_count": len(tasks_phase1) + len(tasks_phase2) + len(tasks_phase3),
                    },
                )
            except Exception as exc:
                persistence["error"] = str(exc)
                logger.error(f"❌ Pipeline FAILED for questionnaire {questionnaire_id[:8]}...: {exc}")

                # 📊 Créer un summary avec status=FAILED
                if questionnaire_id:
                    try:
                        failed_summary_id = supabase_service.save_trip_summary(
                            questionnaire_id=questionnaire_id,
                            questionnaire_data=questionnaire_data,
                            persona_inference=persona_inference,
                            persona_analysis={},
                            trip_json=trip_core if trip_core else None,
                            run_id=run_id,
                            pipeline_status="FAILED",
                        )
                        persistence["trip_summary_id"] = failed_summary_id
                        logger.info(f"✅ Failed trip summary created: {failed_summary_id}")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not create failed trip summary: {e}")

                    tracking_service.mark_pipeline_failed(
                        questionnaire_id=questionnaire_id,
                        error=str(exc),
                    )
        else:
            persistence["error"] = "missing trip payload"
            logger.error(f"❌ Pipeline FAILED: missing trip payload")

            # 📊 Créer un summary avec status=FAILED
            if questionnaire_id:
                try:
                    failed_summary_id = supabase_service.save_trip_summary(
                        questionnaire_id=questionnaire_id,
                        questionnaire_data=questionnaire_data,
                        persona_inference=persona_inference,
                        persona_analysis={},
                        trip_json=None,
                        run_id=run_id,
                        pipeline_status="FAILED",
                    )
                    persistence["trip_summary_id"] = failed_summary_id
                    logger.info(f"✅ Failed trip summary created: {failed_summary_id}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not create failed trip summary: {e}")

                tracking_service.mark_pipeline_failed(
                    questionnaire_id=questionnaire_id,
                    error="missing trip payload",
                )

        final_payload = {
            "run_id": run_id,
            "status": "success" if is_valid else "failed_validation",
            "metadata": {
                "questionnaire_id": self._extract_id(normalized_questionnaire),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            },
            "normalization": normalization.get("metadata", {}),
            "input_context": {"questionnaire": normalized_questionnaire, "persona_inference": persona_inference},
            "pipeline_output": {
                "trip_context": trip_context,
                "destination_choice": destination_choice,
                "tasks_details": tasks_phase1 + tasks_phase2 + tasks_phase3,
            },
            "assembly": {
                "trip": trip_payload,
                "schema_valid": is_valid,
                "schema_error": schema_error,
            },
            "persistence": persistence,
        }

        if should_save:
            self._write_yaml(run_dir / "_SUMMARY_run_output.yaml", final_payload)
            logger.info(f"💾 Résumé complet sauvegardé dans {run_dir}/_SUMMARY_run_output.yaml")

        return final_payload

    def _enrich_builder_from_phase2(
        self,
        builder: IncrementalTripBuilder,
        parsed_phase2: Dict[str, Any],
        mcp_manager: Optional[MCPToolsManager] = None,
    ) -> None:
        """
        Enrichir le builder avec les résultats de PHASE2.

        Extrait les données de:
        - flights_research → set_flight_info()
        - accommodation_research → set_hotel_info()
        - itinerary_design → set_step_* pour chaque step

        Args:
            builder: Le builder de trip à enrichir
            parsed_phase2: Les résultats parsés de PHASE2
            mcp_manager: Le manager d'outils MCP (pour post-processing)
        """
        try:
            # 1. FLIGHTS
            flights_research = parsed_phase2.get("flights_research", {})
            if flights_research:
                flight_quotes = flights_research.get("flight_quotes", {})
                if flight_quotes:
                    # Extract from nested "summary" structure (expected format)
                    summary = flight_quotes.get("summary", {})
                    builder.set_flight_info(
                        flight_from=summary.get("from", "") or flight_quotes.get("from", ""),
                        flight_to=summary.get("to", "") or flight_quotes.get("to", ""),
                        duration=summary.get("duration", "") or flight_quotes.get("duration", ""),
                        flight_type=summary.get("type", "") or flight_quotes.get("type", ""),
                        price=summary.get("price", "") or str(flight_quotes.get("price", "")),
                    )
                    logger.info(f"✅ Vol info set: {summary.get('from', '')} → {summary.get('to', '')}")

            # 2. ACCOMMODATION
            accommodation_research = parsed_phase2.get("accommodation_research", {})
            if accommodation_research:
                lodging_quotes = accommodation_research.get("lodging_quotes", {})
                if lodging_quotes:
                    # Extract from nested "recommended" structure (expected format)
                    recommended = lodging_quotes.get("recommended", {})
                    builder.set_hotel_info(
                        hotel_name=recommended.get("hotel_name", "") or lodging_quotes.get("hotel_name", ""),
                        hotel_rating=float(recommended.get("hotel_rating", 0) or lodging_quotes.get("rating", 0) or 0),
                        price=recommended.get("price_display", "") or str(recommended.get("total_price", "")) or str(lodging_quotes.get("price", "")),
                    )
                    logger.info(f"✅ Hébergement set: {recommended.get('hotel_name', '')} ({recommended.get('hotel_rating', 0)}★)")

            # 3. ITINERARY (le plus important - remplir toutes les steps)
            itinerary_design = parsed_phase2.get("itinerary_design", {})
            if itinerary_design:
                itinerary_plan = itinerary_design.get("itinerary_plan", {})

                # DEBUG: Log what the agent returned
                steps = itinerary_plan.get("steps", [])
                logger.info(f"📊 Agent itinerary_design returned {len(steps)} steps")
                for i, s in enumerate(steps[:3]):  # Log first 3 steps
                    logger.debug(f"  Step {i+1}: title='{s.get('title', '')}', has_gps={bool(s.get('latitude'))}, has_image={bool(s.get('main_image'))}")

                # Extraire hero image
                hero_image = itinerary_plan.get("hero_image") or itinerary_plan.get("main_image", "")
                # 🔧 FIX: Appeler set_hero_image même si vide pour déclencher génération MCP
                # Le builder a un fallback qui génère via images.hero si URL vide
                builder.set_hero_image(hero_image)

                # Extraire les steps
                for step_data in steps:
                    step_number = step_data.get("step_number")
                    if not step_number or step_data.get("is_summary", False):
                        continue  # Skip summary step

                    # Titre
                    try:
                        title = step_data.get("title", "")
                        if title:
                            builder.set_step_title(
                                step_number=step_number,
                                title=title,
                                title_en=step_data.get("title_en", title),
                                subtitle=step_data.get("subtitle", ""),
                                subtitle_en=step_data.get("subtitle_en", ""),
                            )

                        # Image (critique - garantie via MCP si manquante)
                        image_url = step_data.get("main_image", "") or step_data.get("image", "")
                        builder.set_step_image(step_number=step_number, image_url=image_url)

                        # GPS
                        latitude = step_data.get("latitude")
                        longitude = step_data.get("longitude")
                        if latitude and longitude:
                            builder.set_step_gps(
                                step_number=step_number,
                                latitude=float(latitude),
                                longitude=float(longitude),
                            )

                        # Contenu
                        builder.set_step_content(
                            step_number=step_number,
                            why=step_data.get("why", ""),
                            why_en=step_data.get("why_en", ""),
                            tips=step_data.get("tips", ""),
                            tips_en=step_data.get("tips_en", ""),
                            transfer=step_data.get("transfer", ""),
                            transfer_en=step_data.get("transfer_en", ""),
                            suggestion=step_data.get("suggestion", ""),
                            suggestion_en=step_data.get("suggestion_en", ""),
                        )

                        # Météo
                        weather_icon = step_data.get("weather_icon", "")
                        weather_temp = step_data.get("weather_temp", "")
                        if weather_icon or weather_temp:
                            builder.set_step_weather(
                                step_number=step_number,
                                icon=weather_icon,
                                temp=weather_temp,
                                description=step_data.get("weather_description", ""),
                                description_en=step_data.get("weather_description_en", ""),
                            )

                        # Prix et durée
                        price = step_data.get("price", 0)
                        duration = step_data.get("duration", "")
                        if price or duration:
                            builder.set_step_price_duration(
                                step_number=step_number,
                                price=float(price) if price else 0,
                                duration=duration,
                            )

                        # Type
                        step_type = step_data.get("step_type", "")
                        if step_type:
                            builder.set_step_type(step_number=step_number, step_type=step_type)

                    except ValueError as ve:
                        logger.warning(f"⚠️ Skipping step {step_number}: {ve}")
                        continue
                    except Exception as e:
                        logger.error(f"❌ Error processing step {step_number}: {e}")
                        continue

                logger.info(f"✅ Builder enrichi avec {len(steps)} steps depuis PHASE2")

                # 🎨 POST-PROCESSING: Régénérer images + traductions automatiques
                logger.info("🎨 Step 2.5/3: Post-processing enrichment (images + translations)...")
                try:
                    if not mcp_manager:
                        logger.warning("⚠️ MCP manager not available, skipping post-processing")
                        return

                    # 🆕 OPTIMISATION: Utiliser PostProcessor unifié (OPT-11)
                    processor = PostProcessor(mcp_tools=mcp_manager, llm=self._llm)

                    # Récupérer le trip JSON actuel depuis le builder
                    trip_json = builder.get_json()

                    # Enrichir avec images améliorées et traductions (UNE SEULE PASSE)
                    enriched_trip = processor.process_trip(
                        trip_json=trip_json,
                        regenerate_images=True,  # Régénérer images avec prompts enrichis
                        translate_fields=True,   # Traduire FR → EN automatiquement (DeepL + LLM fallback)
                        validate_steps=True,     # Valider structure
                        parallel=True,           # Paralléliser traitement
                        max_workers=6,           # 6 threads parallèles
                    )

                    # Mettre à jour le builder avec le trip enrichi
                    builder.trip_json = enriched_trip

                    logger.info("✅ Post-processing enrichment complete")

                except Exception as pe:
                    logger.warning(f"⚠️ Post-processing enrichment failed: {pe}")
                    logger.warning("   Continuing with original data...")

        except Exception as e:
            logger.error(f"❌ Erreur lors de l'enrichissement depuis PHASE2: {e}", exc_info=True)

    def _merge_trip_data(self, target: Dict[str, Any], source: Dict[str, Any]) -> None:
        """
        Merger les données de source dans target (Priorité à Source pour Phase 3).

        ⚠️ PROTECTION: Les champs générés par scripts Python sont PROTÉGÉS.
        Les agents ne peuvent PAS écraser ces champs critiques.
        """
        # 🔒 CHAMPS PROTÉGÉS: Générés par scripts Python, agents interdits de modifier
        PROTECTED_TRIP_FIELDS = {
            "start_date",           # Généré par script de dates
            "end_date",             # Généré par script de dates
            "total_price",          # Calculé par budget_calculator.py (script)
            "price_flights",        # Calculé par budget_calculator.py
            "price_hotels",         # Calculé par budget_calculator.py
            "price_transport",      # Calculé par budget_calculator.py
            "price_activities",     # Calculé par budget_calculator.py
        }

        # Merger les champs scalaires du trip
        scalar_fields = [
            "destination", "destination_en", "total_days", "main_image",
            "flight_from", "flight_to", "flight_duration", "flight_type",
            "hotel_name", "hotel_rating", "total_price", "total_budget",
            "average_weather", "travel_style", "travel_style_en",
            "start_date", "travelers",
            "price_flights", "price_hotels", "price_transport", "price_activities"
        ]

        for field in scalar_fields:
            # 🔒 PROTECTION: Ne jamais écraser champs protégés
            if field in PROTECTED_TRIP_FIELDS:
                target_value = target.get(field)
                if target_value not in [None, "", 0]:
                    logger.debug(f"🔒 Protected field '{field}' kept from script (target={target_value})")
                    continue  # Garder valeur script, ignorer agent

            source_value = source.get(field)
            # Priorité à Source si valeur présente
            if source_value not in [None, "", 0]:
                target[field] = source_value

        # Merger les steps
        source_steps = source.get("steps", [])
        target_steps = target.get("steps", [])

        if not source_steps:
            return

        # Créer un mapping step_number -> step pour un accès rapide
        # Gérer les types str/int pour step_number
        target_steps_map = {}
        for s in target_steps:
            sn = s.get("step_number")
            if sn is not None:
                target_steps_map[str(sn)] = s
                target_steps_map[int(sn)] = s

        logger.info(f"🔄 Merging {len(source_steps)} steps from Phase 3 into {len(target_steps)} existing steps")

        for source_step in source_steps:
            step_num = source_step.get("step_number")
            if step_num is None:
                continue

            target_step = target_steps_map.get(step_num) or target_steps_map.get(str(step_num))

            if not target_step:
                # Step n'existe pas dans target, l'ajouter
                target_steps.append(source_step)
                logger.debug(f"  ➕ Added new step {step_num}")
                continue

            # 🔒 CHAMPS PROTÉGÉS AU NIVEAU STEP: Générés par scripts, agents interdits
            PROTECTED_STEP_FIELDS = {
                "latitude",        # Généré par StepTemplateGenerator (geo.place)
                "longitude",       # Généré par StepTemplateGenerator (geo.place)
                "main_image",      # Généré par ImageGenerator (images.background)
                "step_type",       # Mappé par StepTemplateGenerator
                "duration",        # Calculé par scripts de métadonnées
            }

            # Step existe, merger les champs (Source overwrites Target)
            step_fields = [
                "title", "title_en", "subtitle", "subtitle_en",
                "main_image", "step_type", "is_summary",
                "latitude", "longitude",
                "why", "why_en", "tips", "tips_en",
                "transfer", "transfer_en", "suggestion", "suggestion_en",
                "weather_icon", "weather_temp", "weather_description", "weather_description_en",
                "price", "duration", "day_number"
            ]

            for field in step_fields:
                source_value = source_step.get(field)

                # 🔒 PROTECTION STRICTE: GPS coordinates
                if field in ["latitude", "longitude"]:
                    target_value = target_step.get(field)
                    # Ne JAMAIS écraser GPS valide avec 0 ou None
                    if target_value not in [None, 0, "", "0"]:
                        # GPS existe dans target (script), ne pas écraser
                        if source_value in [None, 0, "", "0"]:
                            logger.debug(f"🔒 Step {step_num}: GPS '{field}' protected (script={target_value})")
                            continue
                        # Même si source a GPS, préférer script (plus fiable)
                        logger.debug(f"🔒 Step {step_num}: GPS '{field}' kept from script (script={target_value}, agent={source_value})")
                        continue

                # 🔒 PROTECTION STRICTE: Images Supabase
                if field == "main_image":
                    target_image = target_step.get("main_image")
                    # Ne JAMAIS écraser image Supabase valide
                    if target_image and "supabase" in str(target_image):
                        if not source_value or "supabase" not in str(source_value):
                            logger.debug(f"🔒 Step {step_num}: Image protected from script")
                            continue
                        # Même avec source Supabase, garder script (folder correct)
                        logger.debug(f"🔒 Step {step_num}: Image kept from script")
                        continue

                # 🔒 PROTECTION: step_type et duration générés par scripts
                if field in PROTECTED_STEP_FIELDS:
                    target_value = target_step.get(field)
                    if target_value not in [None, "", 0]:
                        logger.debug(f"🔒 Step {step_num}: '{field}' protected (script={target_value})")
                        continue

                # Default: Source wins if it has value (pour champs non protégés)
                if source_value not in [None, ""]:
                    target_step[field] = source_value
                    if field == "title":
                        logger.debug(f"    📝 Step {step_num}: Title updated to '{source_value}'")

            # Merger images array (additionner sans doublons)
            source_images = source_step.get("images", [])
            target_images = target_step.get("images", [])
            if source_images:
                for img in source_images:
                    if img not in target_images:
                        target_images.append(img)

            # Merger summary_stats
            if source_step.get("summary_stats"):
                target_step["summary_stats"] = source_step["summary_stats"]

        target["steps"] = target_steps

    def _enrich_builder_from_phase3(
        self,
        builder: IncrementalTripBuilder,
        parsed_phase3: Dict[str, Any],
    ) -> None:
        """
        Enrichir le builder avec les résultats de PHASE3.

        Extrait les données de:
        - budget_calculation → set_prices()
        - final_assembly → remplacer complètement le trip avec les données de l'agent
        """
        try:
            # 1. Enrichir avec les prix depuis budget_calculation
            budget_calculation = parsed_phase3.get("budget_calculation", {})
            if budget_calculation:
                # Handle nested structure common in agent output
                budget_data = budget_calculation.get("budget_summary", budget_calculation)
                totals = budget_data.get("totals", {}) if isinstance(budget_data, dict) else {}
                breakdown = budget_data.get("breakdown", {}) if isinstance(budget_data, dict) else {}
                
                # Extraire les prix (supporte nesting breakdown)
                total_price = totals.get("grand_total") or \
                             budget_data.get("total_price") or \
                             budget_data.get("total_budget") or \
                             budget_data.get("estimated_total", "")

                flights_data = breakdown.get("flights", {})
                price_flights = flights_data.get("total") or \
                               budget_data.get("flight_cost") or \
                               budget_data.get("flights_cost", "")

                hotels_data = breakdown.get("accommodation", {})
                price_hotels = hotels_data.get("total") or \
                              budget_data.get("accommodation_cost") or \
                              budget_data.get("lodging_cost", "")

                transport_data = breakdown.get("transport_local", {})
                price_transport = transport_data.get("total") or \
                                 budget_data.get("transport_cost") or \
                                 budget_data.get("local_transport_cost", "")

                activities_data = breakdown.get("activities", {})
                price_activities = activities_data.get("total") or \
                                  budget_data.get("activities_cost", "")

                builder.set_prices(
                    total_price=str(total_price) if total_price else "",
                    price_flights=str(price_flights) if price_flights else "",
                    price_hotels=str(price_hotels) if price_hotels else "",
                    price_transport=str(price_transport) if price_transport else "",
                    price_activities=str(price_activities) if price_activities else "",
                )

                logger.info(f"✅ Builder enrichi avec le budget depuis PHASE3")

            # 2. 🆕 MERGER les données de final_assembly (sans écraser Phase 2)
            final_assembly = parsed_phase3.get("final_assembly", {})
            if final_assembly and "trip" in final_assembly:
                assembled_trip = final_assembly["trip"]
                logger.info(f"🔧 Merge des données de final_assembly avec le trip existant...")

                # MERGER intelligemment au lieu de remplacer
                self._merge_trip_data(builder.trip_json, assembled_trip)

                logger.info(f"✅ Trip enrichi avec les données de final_assembly")

        except Exception as e:
            logger.error(f"❌ Erreur lors de l'enrichissement depuis PHASE3: {e}", exc_info=True)

    def _validate_and_complete_structure_plan(
        self,
        trip_structure_plan: Dict[str, Any],
        total_days: int,
        rhythm: str
    ) -> Dict[str, Any]:
        """
        Valide et complète le daily_distribution si l'agent n'a pas généré tous les jours.

        Bug fix: L'agent plan_trip_structure ne génère souvent que 5-6 jours au lieu de tous les jours.
        Cette fonction complète automatiquement en extrapolant le pattern des jours existants.

        Args:
            trip_structure_plan: Plan structurel retourné par l'agent
            total_days: Nombre total de jours du voyage
            rhythm: Rythme du voyageur (relaxed/balanced/intense)

        Returns:
            Plan structurel complété avec tous les jours
        """
        daily_distribution = trip_structure_plan.get("daily_distribution", [])

        if not daily_distribution:
            logger.warning("⚠️ daily_distribution vide, création d'un plan par défaut")
            # Créer un plan par défaut
            steps_per_day = {"relaxed": 1, "balanced": 2, "intense": 2}.get(rhythm, 2)
            daily_distribution = [
                {"day": i, "steps_count": steps_per_day, "zone": "Centre", "intensity": "medium"}
                for i in range(1, total_days + 1)
            ]
            trip_structure_plan["daily_distribution"] = daily_distribution
            trip_structure_plan["total_steps_planned"] = total_days * steps_per_day
            return trip_structure_plan

        # Vérifier combien de jours ont été générés
        max_day_generated = max([d.get("day", 0) for d in daily_distribution])

        if max_day_generated >= total_days:
            logger.info(f"✅ daily_distribution complet ({max_day_generated} jours)")
            return trip_structure_plan

        # 🛡️ CORRECTION: Compléter les jours manquants
        logger.warning(
            f"⚠️ daily_distribution incomplet: {max_day_generated}/{total_days} jours générés. "
            f"Complétion automatique..."
        )

        # Analyser le pattern des jours existants
        if daily_distribution:
            # Calculer moyenne de steps_count
            avg_steps = sum([d.get("steps_count", 1) for d in daily_distribution]) / len(daily_distribution)
            avg_steps = round(avg_steps)

            # Extraire zones et intensity les plus fréquentes
            zones = [d.get("zone", "Centre") for d in daily_distribution]
            intensities = [d.get("intensity", "medium") for d in daily_distribution]
            most_common_zone = max(set(zones), key=zones.count) if zones else "Centre"
            most_common_intensity = max(set(intensities), key=intensities.count) if intensities else "medium"

            # Compléter les jours manquants en répétant le pattern
            for day_num in range(max_day_generated + 1, total_days + 1):
                # Alterner légèrement les steps_count pour varier
                steps_count = avg_steps
                if day_num % 3 == 0:  # Tous les 3 jours, jour plus calme
                    steps_count = max(1, avg_steps - 1)

                daily_distribution.append({
                    "day": day_num,
                    "steps_count": steps_count,
                    "zone": most_common_zone,
                    "intensity": most_common_intensity if steps_count == avg_steps else "low"
                })

        # Recalculer total_steps_planned
        total_steps = sum([d.get("steps_count", 1) for d in daily_distribution])
        trip_structure_plan["total_steps_planned"] = total_steps
        trip_structure_plan["daily_distribution"] = daily_distribution

        logger.info(f"✅ daily_distribution complété: {len(daily_distribution)} jours, {total_steps} steps total")

        return trip_structure_plan

    def _validate_and_fix_trip_data(self, builder: IncrementalTripBuilder) -> None:
        """
        Vérifie et répare les données critiques (code, images) avant sauvegarde finale.
        Assure la robustesse demandée par l'utilisateur.
        """
        trip = builder.trip_json
        
        # 1. 🛡️ TRIP CODE (Obligatoire)
        if not trip.get("code"):
            logger.warning("⚠️ CRITICAL: Trip code missing in final payload! Regenerating...")
            dest = trip.get("destination", "TRIP")
            import uuid
            from datetime import datetime
            clean_dest = "".join(c for c in dest if c.isalnum()).upper()[:10]
            year = datetime.utcnow().year
            uid = str(uuid.uuid4())[:6].upper()
            trip["code"] = f"{clean_dest}-{year}-{uid}"
            logger.info(f"✅ Trip code fixed: {trip['code']}")

        # 2. 🛡️ IMAGES (Super important)
        if not trip.get("main_image") or trip.get("main_image") == "":
            logger.warning("⚠️ Main image missing, attempting fix...")
            
            # A. Try to grab valid image from any step
            steps = trip.get("steps", [])
            found = False
            for s in steps:
                img = s.get("main_image")
                if img and "supabase.co" in img:
                    trip["main_image"] = img
                    logger.info(f"✅ Main image fixed using image from step {s.get('step_number')}")
                    found = True
                    break
            
            # B. If still missing, force generation/fallback mechanism
            if not found:
                logger.warning("⚠️ No valid image found in steps, triggering builder fallback...")
                builder.set_hero_image("") # Will trigger MCP generation or Unsplash fallback

    def _create_agent(self, name: str, config: Dict[str, Any], tools: List[Any]) -> Agent:
        """Crée un agent avec sa configuration complète."""
        agent_params = {
            "role": config["role"],
            "goal": config["goal"],
            "backstory": config["backstory"],
            "allow_delegation": False,  # Strictement interdit
            "verbose": self._verbose,
            "tools": tools,
            "llm": self._llm,
            "max_iter": config.get("max_iter", 15),
        }
        
        # ✅ NOUVEAU : Activer reasoning si configuré
        if config.get("reasoning", False):
            agent_params["reasoning"] = True
            if "max_reasoning_attempts" in config:
                agent_params["max_reasoning_attempts"] = config["max_reasoning_attempts"]
        
        # ✅ NOUVEAU : Activer memory si configuré
        if config.get("memory", False):
            agent_params["memory"] = True
        
        # ✅ NOUVEAU : Injecter date si configuré
        # CrewAI gère automatiquement inject_date via le paramètre
        # Pas besoin de code supplémentaire si le paramètre existe dans la config
        
        return Agent(**agent_params)

    def _collect_tasks_output(
        self,
        crew_output: Any,
        should_save: bool,
        run_dir: Path,
        phase_label: str,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Parse les tasks outputs CrewAI et retourne (liste détaillée, mapping par nom)."""

        tasks_data: List[Dict[str, Any]] = []
        parsed_by_name: Dict[str, Any] = {}

        if hasattr(crew_output, "tasks_output"):
            for idx, task_out in enumerate(crew_output.tasks_output, start=1):
                task_name = getattr(task_out, "name", f"task_{idx}")
                raw_content = getattr(task_out, "raw", "")
                structured_content = self._parse_yaml_content(raw_content)

                record = {
                    "task_name": str(task_name),
                    "agent": getattr(task_out, "agent", ""),
                    "structured_output": structured_content,
                    "raw_output": raw_content,
                    "phase": phase_label,
                    "order": idx,
                }
                tasks_data.append(record)
                parsed_by_name[task_name] = structured_content if isinstance(structured_content, dict) else {"raw": structured_content}

                if should_save:
                    phase_dir = run_dir / phase_label / f"step_{idx}_{task_name}"
                    phase_dir.mkdir(parents=True, exist_ok=True)
                    self._write_yaml(phase_dir / "output.yaml", record)
                    logger.info(f"📁 {phase_label} - Step {idx}: {task_name} → {phase_dir}")

        return tasks_data, parsed_by_name

    def _run_with_mocked_crew(
        self,
        questionnaire_data: Dict[str, Any],
        persona_inference: Dict[str, Any],
        run_id: str,
        run_dir: Optional[Path],
    ) -> Dict[str, Any]:
        """Chemin d'exécution simplifié pour les tests unitaires avec crew factice."""

        crew = self._crew_builder()
        inputs = {
            "questionnaire": questionnaire_data,
            "persona_context": persona_inference,
            "input_payload": {"questionnaire": questionnaire_data, "persona": persona_inference},
        }

        crew_output = crew.kickoff(inputs)

        raw_output = getattr(crew_output, "raw", crew_output)
        parsed: Optional[Dict[str, Any]] = None

        if hasattr(crew_output, "json_dict") and crew_output.json_dict is not None:
            parsed = crew_output.json_dict
        elif isinstance(crew_output, dict):
            parsed = crew_output
        elif isinstance(crew_output, str):
            try:
                parsed = yaml.safe_load(crew_output)
            except Exception:
                parsed = None
        elif isinstance(raw_output, str):
            try:
                parsed = yaml.safe_load(raw_output)
            except Exception:
                parsed = None

        normalized_trip_request = parsed.get("normalized_trip_request", {}) if isinstance(parsed, dict) else {}
        try:
            normalized_questionnaire = normalize_questionnaire(questionnaire_data).get("questionnaire", {})
        except Exception:
            normalized_questionnaire = {}

        def _fill_missing(target: Dict[str, Any], source: Dict[str, Any]) -> None:
            for key, value in (source or {}).items():
                if key not in target or target[key] is None:
                    target[key] = value
                elif isinstance(target.get(key), dict) and isinstance(value, dict):
                    _fill_missing(target[key], value)

        if isinstance(normalized_trip_request, dict) and normalized_questionnaire:
            for key in ("trip_frame", "travel_party", "budget"):
                source = normalized_questionnaire.get(key)
                if source:
                    if key not in normalized_trip_request or not normalized_trip_request.get(key):
                        normalized_trip_request[key] = source
                    elif isinstance(normalized_trip_request.get(key), dict) and isinstance(source, dict):
                        _fill_missing(normalized_trip_request[key], source)

        def _parse_amount(value: Any) -> Optional[int]:
            digits = re.sub(r"[^0-9]", "", str(value) if value is not None else "")
            return int(digits) if digits else None

        def _enrich_from_questionnaire() -> None:
            data = questionnaire_data.get("questionnaire", questionnaire_data) or {}

            trip_frame = normalized_trip_request.setdefault("trip_frame", {})
            origin = trip_frame.setdefault("origin", {})
            if origin.get("city") is None:
                if isinstance(data.get("departure_location"), dict):
                    origin["city"] = data["departure_location"].get("city")
                    origin["country"] = data["departure_location"].get("country")
                elif data.get("lieu_depart"):
                    parts = [p.strip() for p in str(data.get("lieu_depart", "")).split(",") if p.strip()]
                    if parts:
                        origin["city"] = origin.get("city") or parts[0]
                        if len(parts) > 1:
                            origin["country"] = origin.get("country") or parts[1]

            dates = trip_frame.setdefault("dates", {})
            dates_type = data.get("dates_type") or data.get("type_dates")
            if (not dates.get("type")) and dates_type:
                dates["type"] = dates_type

            if dates.get("type") == "flexible":
                if isinstance(data.get("departure_window"), dict):
                    dates["range"] = data["departure_window"]
                    if not dates.get("departure_dates"):
                        dates["departure_dates"] = [dates["range"].get("start"), dates["range"].get("end")]
                elif data.get("date_depart_approximative"):
                    try:
                        base_date = datetime.fromisoformat(str(data["date_depart_approximative"]))
                        delta = _parse_amount(data.get("flexibilite")) or 3
                        nights = _parse_amount(data.get("duree")) or 0
                        start = (base_date - timedelta(days=delta)).date().isoformat()
                        end = (base_date + timedelta(days=delta)).date().isoformat()
                        dates["range"] = {"start": start, "end": end}
                        dates["departure_dates"] = [start, end]
                        dates["return_dates"] = [
                            (datetime.fromisoformat(start) + timedelta(days=nights)).date().isoformat(),
                            (datetime.fromisoformat(end) + timedelta(days=nights)).date().isoformat(),
                        ]
                        dates["duration_nights"] = nights
                    except Exception:
                        pass

                if isinstance(data.get("return_window"), dict):
                    dates["return_range"] = data["return_window"]
                    if not dates.get("return_dates"):
                        dates["return_dates"] = [dates["return_range"].get("start"), dates["return_range"].get("end")]
                elif dates.get("departure_dates") and data.get("duree"):
                    try:
                        nights = _parse_amount(data.get("duree")) or 0
                        start = datetime.fromisoformat(dates["departure_dates"][0])
                        ret_start = (start + timedelta(days=nights)).date().isoformat()
                        ret_end = (
                            datetime.fromisoformat(dates["departure_dates"][-1])
                            + timedelta(days=nights)
                        ).date().isoformat()
                        dates["return_dates"] = [ret_start, ret_end]
                        dates.setdefault("range", {"start": dates["departure_dates"][0], "end": dates["departure_dates"][-1]})
                        dates["duration_nights"] = nights
                    except Exception:
                        pass

            travel_party = normalized_trip_request.setdefault("travel_party", {})
            if travel_party.get("travelers_count") is None:
                count = _parse_amount(data.get("number_of_travelers")) or data.get("nombre_voyageurs")
                travel_party["travelers_count"] = count
            if not travel_party.get("group_type"):
                group = str(data.get("travel_group") or "").lower()
                if "famille" in group:
                    travel_party["group_type"] = "family"
                elif travel_party.get("travelers_count") == 2:
                    travel_party["group_type"] = "couple"
                else:
                    travel_party["group_type"] = "group"

            budget = normalized_trip_request.setdefault("budget", {})
            if budget.get("currency") is None:
                if isinstance(data.get("budget"), dict):
                    budget["currency"] = data["budget"].get("currency")
                else:
                    budget["currency"] = data.get("devise_budget")

            per_person_min = _parse_amount(
                data.get("budget", {}).get("amount_per_person") if isinstance(data.get("budget"), dict) else data.get("budget_par_personne")
            )
            per_person_max = _parse_amount(
                data.get("budget", {}).get("amount_per_person_max") if isinstance(data.get("budget"), dict) else data.get("budget_max_par_personne")
            )

            if per_person_min or per_person_max:
                budget["per_person_range"] = {"min": per_person_min or per_person_max, "max": per_person_max or per_person_min}

            if travel_party.get("travelers_count") and budget.get("per_person_range"):
                count = travel_party["travelers_count"]
                per_range = budget["per_person_range"]
                budget["group_range"] = {
                    "min": per_range.get("min", 0) * count,
                    "max": per_range.get("max", 0) * count,
                }
                budget["estimated_total_group"] = budget["group_range"].get("max")

        _enrich_from_questionnaire()

        persona_analysis: Dict[str, Any]
        if isinstance(parsed, dict):
            persona_analysis = parsed.get("persona_analysis") or parsed
            persona_analysis.setdefault("persona_summary", "")
            persona_analysis.setdefault("pros", [])
            persona_analysis.setdefault("cons", [])
            persona_analysis.setdefault("critical_needs", [])
            persona_analysis.setdefault("non_critical_preferences", [])
            persona_analysis.setdefault("user_goals", [])
            persona_analysis.setdefault("narrative", "")
            persona_analysis.setdefault("analysis_notes", "")
            persona_analysis.setdefault("challenge_summary", "")
            persona_analysis.setdefault("challenge_actions", [])
            persona_analysis.setdefault("normalized_trip_request", normalized_trip_request)
        else:
            persona_analysis = {
                "persona_summary": "Analyse non structurée",
                "pros": [],
                "cons": [],
                "critical_needs": [],
                "non_critical_preferences": [],
                "user_goals": [],
                "narrative": "",
                "analysis_notes": "La réponse de l'agent ne suit pas un format structuré.",
                "raw_response": raw_output,
                "challenge_summary": "",
                "challenge_actions": [],
                "normalized_trip_request": normalized_trip_request,
            }

        result = {
            "run_id": run_id,
            "questionnaire_id": self._extract_id(questionnaire_data),
            "normalized_trip_request": normalized_trip_request,
            "persona_analysis": persona_analysis,
        }

        if run_dir:
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "run_output.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            if hasattr(crew_output, "tasks_output") and crew_output.tasks_output:
                tasks_dir = run_dir / "tasks"
                tasks_dir.mkdir(parents=True, exist_ok=True)
                for task_out in crew_output.tasks_output:
                    task_record = {
                        "task_name": getattr(task_out, "name", ""),
                        "agent": getattr(task_out, "agent", ""),
                        "description": getattr(task_out, "description", ""),
                        "json_output": getattr(task_out, "json_dict", {}) or {},
                        "raw_output": getattr(task_out, "raw", ""),
                        "expected_output": getattr(task_out, "expected_output", None),
                    }
                    task_path = tasks_dir / f"{task_record['task_name']}.json"
                    task_path.write_text(json.dumps(task_record, ensure_ascii=False, indent=2), encoding="utf-8")

        return result

    def _parse_yaml_content(self, content: str) -> Any:
        """Nettoie et parse une chaîne contenant potentiellement du YAML."""
        if not content:
            return None

        content = content.strip()

        # Cas 1: Extraire le contenu d'un bloc ```yaml ... ```
        yaml_block_match = re.search(r"```yaml\s*\n(.*?)\n```", content, re.DOTALL)
        if yaml_block_match:
            yaml_content = yaml_block_match.group(1).strip()
            try:
                return yaml.safe_load(yaml_content)
            except yaml.YAMLError:
                logger.warning("⚠️ YAML invalide dans le bloc markdown")

        # Cas 2: Extraire TOUS les blocs ``` ... ``` et tester chacun
        code_blocks = re.findall(r"```\s*\n(.*?)\n```", content, re.DOTALL)
        for code_content in reversed(code_blocks):  # Tester du dernier au premier
            code_content = code_content.strip()
            try:
                parsed = yaml.safe_load(code_content)
                # Vérifier que c'est un dict valide (pas juste du texte)
                if isinstance(parsed, dict) and len(parsed) > 0:
                    return parsed
            except yaml.YAMLError:
                continue  # Essayer le bloc suivant

        # Cas 3: Pas de bloc markdown, nettoyer et parser directement
        cleaned = re.sub(r"^```yaml\s*", "", content)
        cleaned = re.sub(r"^```\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            return yaml.safe_load(cleaned)
        except yaml.YAMLError:
            logger.warning("⚠️ Impossible de parser le YAML, retour du contenu brut.")
            return content

    def _write_yaml(self, path: Path, data: Any) -> None:
        """Écrit un fichier YAML proprement."""
        try:
            with path.open("w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, sort_keys=False, indent=2)
        except Exception as e:
            logger.error(f"Erreur écriture fichier {path}: {e}")

    def _load_yaml_config(self, filename: str) -> Dict[str, Any]:
        path = self._config_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Config manquante: {path}")
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _generate_run_id(self, data: Dict[str, Any]) -> str:
        qid = self._extract_id(data)
        suffix = uuid4().hex[:8]
        return f"{qid}-{suffix}" if qid else f"run-{suffix}"

    def _extract_id(self, data: Dict[str, Any]) -> str:
        return str(data.get("id") or data.get("questionnaire_id") or "")

    def _build_crew(self, **kwargs: Any) -> Crew:
        """Fabrique un Crew (surchargé dans les tests pour injecter un mock)."""

        return Crew(**kwargs)

# Instance globale
travliaq_crew_pipeline = CrewPipeline()

def run_pipeline_with_inputs(**kwargs):
    return travliaq_crew_pipeline.run(**kwargs)


def run_pipeline_from_payload(payload: Any, *, pipeline: CrewPipeline | None = None) -> Dict[str, Any]:
    """Helper pour exécuter la pipeline à partir d'un payload brut.

    Le payload peut être un dictionnaire ou une chaîne YAML/JSON. Les tests
    unitaires exigent la présence de ``questionnaire_data``; une ``ValueError``
    est levée si ce champ manque.
    """

    if isinstance(payload, str):
        try:
            payload_dict = yaml.safe_load(payload) or {}
        except Exception:
            payload_dict = {}
    elif isinstance(payload, dict):
        payload_dict = payload
    else:
        raise TypeError("payload must be a dict or YAML/JSON string")

    questionnaire_data = payload_dict.get("questionnaire_data") or payload_dict.get("questionnaire")
    if questionnaire_data is None:
        raise ValueError("questionnaire_data is required")

    persona_inference = payload_dict.get("persona_inference") or payload_dict.get("persona") or {}
    metadata = payload_dict.get("metadata") or payload_dict.get("payload_metadata")

    pipeline_instance = pipeline or travliaq_crew_pipeline
    return pipeline_instance.run(
        questionnaire_data=questionnaire_data,
        persona_inference=persona_inference,
        payload_metadata=metadata,
    )
