"""Pipeline CrewAI complète (scripts + agents) pour générer le YAML/JSON Trip."""

from __future__ import annotations

import logging
import os
import re
import json
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
)
from app.services.supabase_service import supabase_service

logger = logging.getLogger(__name__)

# Variable globale pour éviter l'initialisation multiple du logging
_logging_initialized = False


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
        self._output_dir = Path(output_dir) if output_dir is not None else Path(settings.crew_output_dir)
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
        logger.info(f"🚀 Lancement Pipeline CrewAI (Run ID: {run_id})")

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
        if settings.mcp_server_url:
            try:
                mcp_tools = get_mcp_tools(settings.mcp_server_url)
                logger.info(f"✅ {len(mcp_tools)} outils MCP chargés.")
            except Exception as e:
                logger.warning(f"⚠️ Erreur chargement MCP: {e}")

        # 3. Agents nécessaires (nouvelle architecture - 7 agents)
        context_builder = self._create_agent("trip_context_builder", agents_config["trip_context_builder"], tools=[])
        strategist = self._create_agent("destination_strategist", agents_config["destination_strategist"], tools=mcp_tools)
        flight_specialist = self._create_agent("flights_specialist", agents_config["flights_specialist"], tools=mcp_tools)
        accommodation_specialist = self._create_agent("accommodation_specialist", agents_config["accommodation_specialist"], tools=mcp_tools)
        itinerary_designer = self._create_agent("itinerary_designer", agents_config["itinerary_designer"], tools=mcp_tools)
        budget_calculator = self._create_agent("budget_calculator", agents_config["budget_calculator"], tools=[])
        final_assembler = self._create_agent("final_assembler", agents_config["final_assembler"], tools=[])

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
        destination_choice = parsed_phase1.get("destination_strategy", {}).get("destination_choice", {})

        # Dériver l'intent depuis trip_context (plus simple que normalized_trip_request)
        trip_intent = self._derive_trip_intent(normalized_questionnaire, trip_context)

        # 5. Phase 2 - Research (conditionnelle selon help_with)
        phase2_tasks: List[Task] = []
        phase2_agents: List[Agent] = []

        # Convertir outputs en YAML pour prompts
        trip_context_yaml = yaml.dump(trip_context, allow_unicode=True, sort_keys=False)
        destination_choice_yaml = yaml.dump(destination_choice, allow_unicode=True, sort_keys=False)

        # Extraire dates validées depuis trip_context
        dates_info = trip_context.get("dates", {}) or {}
        departure_window = dates_info.get("departure_window") or {}
        return_window = dates_info.get("return_window") or {}
        departure_dates = dates_info.get("departure_date") or departure_window.get("start") or "Non spécifiée"
        return_dates = dates_info.get("return_date") or return_window.get("end") or "Non spécifiée"

        inputs_phase2 = {
            "trip_context": trip_context_yaml,
            "destination_choice": destination_choice_yaml,
            "current_year": datetime.now().year,
            "validated_departure_dates": departure_dates,
            "validated_return_dates": return_dates,
        }

        # Ajouter les agents conditionnellement
        flight_task: Optional[Task] = None
        if trip_intent.assist_flights:
            flight_task = Task(name="flights_research", agent=flight_specialist, **tasks_config["flights_research"])
            phase2_tasks.append(flight_task)
            phase2_agents.append(flight_specialist)

        lodging_task: Optional[Task] = None
        if trip_intent.assist_accommodation:
            lodging_task = Task(name="accommodation_research", agent=accommodation_specialist, **tasks_config["accommodation_research"])
            phase2_tasks.append(lodging_task)
            phase2_agents.append(accommodation_specialist)

        itinerary_task: Optional[Task] = None
        if trip_intent.assist_activities:
            itinerary_task = Task(name="itinerary_design", agent=itinerary_designer, **tasks_config["itinerary_design"])
            phase2_tasks.append(itinerary_task)
            phase2_agents.append(itinerary_designer)

        # Lancer Phase 2 seulement si au moins un service demandé
        parsed_phase2 = {}
        tasks_phase2 = []
        if phase2_tasks:
            crew_phase2 = self._crew_builder(
                agents=phase2_agents,
                tasks=phase2_tasks,
                verbose=self._verbose,
                process=Process.sequential,
            )
            output_phase2 = crew_phase2.kickoff(inputs=inputs_phase2)
            tasks_phase2, parsed_phase2 = self._collect_tasks_output(output_phase2, should_save, run_dir, phase_label="PHASE2_RESEARCH")

        # 6. Phase 3 - Budget + Assembly
        budget_task = Task(name="budget_calculation", agent=budget_calculator, **tasks_config["budget_calculation"])
        final_task = Task(name="final_assembly", agent=final_assembler, context=[budget_task], **tasks_config["final_assembly"])

        crew_phase3 = self._crew_builder(
            agents=[budget_calculator, final_assembler],
            tasks=[budget_task, final_task],
            verbose=self._verbose,
            process=Process.sequential,
        )

        # Convertir outputs Phase 2 en YAML pour prompts
        flight_quotes_yaml = yaml.dump(parsed_phase2.get("flights_research", {}).get("flight_quotes", {}), allow_unicode=True, sort_keys=False)
        lodging_quotes_yaml = yaml.dump(parsed_phase2.get("accommodation_research", {}).get("lodging_quotes", {}), allow_unicode=True, sort_keys=False)
        itinerary_plan_yaml = yaml.dump(parsed_phase2.get("itinerary_design", {}).get("itinerary_plan", {}), allow_unicode=True, sort_keys=False)

        inputs_phase3 = {
            "trip_context": trip_context_yaml,
            "destination_choice": destination_choice_yaml,
            "flight_quotes": flight_quotes_yaml,
            "lodging_quotes": lodging_quotes_yaml,
            "itinerary_plan": itinerary_plan_yaml,
        }

        output_phase3 = crew_phase3.kickoff(inputs=inputs_phase3)
        tasks_phase3, parsed_phase3 = self._collect_tasks_output(output_phase3, should_save, run_dir, phase_label="PHASE3_ASSEMBLY")

        # Extraire le JSON final depuis l'agent final_assembler
        trip_payload = parsed_phase3.get("final_assembly", {})

        # Validation Schema
        is_valid, schema_error = False, "No trip payload generated"
        if "trip" in trip_payload and isinstance(trip_payload.get("trip"), dict):
            is_valid, schema_error = validate_trip_schema(trip_payload.get("trip", {}))
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

        trip_core = trip_payload.get("trip")
        if trip_core:
            try:
                if is_valid:
                    trip_id = supabase_service.insert_trip_from_json(trip_core)
                    persistence["inserted_via_function"] = bool(trip_id)
                    persistence["supabase_trip_id"] = trip_id

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
        else:
            persistence["error"] = "missing trip payload"

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
            
        # Nettoyage des balises markdown ```yaml ... ```
        cleaned = re.sub(r"^```yaml\s*", "", content.strip())
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
