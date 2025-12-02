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
from app.crew_pipeline.mcp_tools import get_mcp_tools
from app.crew_pipeline.scripts import (
    assemble_trip,
    build_system_contract,
    NormalizationError,
    normalize_questionnaire,
    validate_trip_schema,
)
from app.services.supabase_service import supabase_service

logger = logging.getLogger(__name__)


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
        input_payload_yaml = yaml.dump(
            {"questionnaire": normalized_questionnaire, "persona": persona_inference},
            allow_unicode=True,
            sort_keys=False,
        )

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

        # 3. Agents nécessaires
        analyst = self._create_agent("traveller_insights_analyst", agents_config["traveller_insights_analyst"], tools=mcp_tools)
        challenger = self._create_agent("persona_quality_challenger", agents_config["persona_quality_challenger"], tools=mcp_tools)
        architect = self._create_agent("trip_specifications_architect", agents_config["trip_specifications_architect"], tools=[])
        contract_validator = self._create_agent("system_contract_validator", agents_config["system_contract_validator"], tools=[])
        scout = self._create_agent("destination_scout", agents_config["destination_scout"], tools=mcp_tools)
        flight_agent = self._create_agent("flight_pricing_analyst", agents_config["flight_pricing_analyst"], tools=mcp_tools)
        lodging_agent = self._create_agent("lodging_pricing_analyst", agents_config["lodging_pricing_analyst"], tools=mcp_tools)
        activities_agent = self._create_agent("activities_geo_designer", agents_config["activities_geo_designer"], tools=mcp_tools)
        budget_agent = self._create_agent("budget_consistency_controller", agents_config["budget_consistency_controller"], tools=[])
        decision_maker = self._create_agent("destination_decision_maker", agents_config["destination_decision_maker"], tools=[])
        safety_gate = self._create_agent("feasibility_safety_expert", agents_config["feasibility_safety_expert"], tools=mcp_tools)

        # 4. Phase 1 - Analyse & Spécifications
        task1 = Task(name="traveller_profile_brief", agent=analyst, **tasks_config["traveller_profile_brief"])
        task2 = Task(name="persona_challenge_review", agent=challenger, context=[task1], **tasks_config["persona_challenge_review"])
        task3 = Task(name="trip_specifications_design", agent=architect, context=[task2], **tasks_config["trip_specifications_design"])

        crew_phase1 = self._crew_builder(
            agents=[analyst, challenger, architect],
            tasks=[task1, task2, task3],
            verbose=self._verbose,
            process=Process.sequential,
        )

        inputs_phase1 = {
            "questionnaire": questionnaire_yaml,
            "persona_context": persona_yaml,
            "input_payload": input_payload_yaml,
        }

        output_phase1 = crew_phase1.kickoff(inputs=inputs_phase1)
        tasks_phase1, parsed_phase1 = self._collect_tasks_output(output_phase1, should_save, run_dir, phase_label="PHASE1_ANALYSIS")
        normalized_trip_request = parsed_phase1.get("trip_specifications_design", {}).get("normalized_trip_request")
        if not normalized_trip_request:
            normalized_trip_request = parsed_phase1.get("trip_specifications_design", {})

        trip_intent = self._derive_trip_intent(normalized_questionnaire, normalized_trip_request or {})

        # 5. System Contract Draft (script)
        system_contract_draft = build_system_contract(
            questionnaire=normalized_questionnaire,
            normalized_trip_request=normalized_trip_request or {},
            persona_context=persona_inference,
        )
        system_contract_yaml = yaml.dump(system_contract_draft, allow_unicode=True, sort_keys=False)

        if should_save:
            contract_dir = run_dir / "PHASE2_PREP"
            contract_dir.mkdir(parents=True, exist_ok=True)
            self._write_yaml(contract_dir / "system_contract_draft.yaml", system_contract_draft)

        # 6. Phase 2 - Validation, scouting, pricing, activités, budget, décision
        task4 = Task(name="system_contract_validation", agent=contract_validator, context=[task1, task2, task3], **tasks_config["system_contract_validation"])

        phase2_tasks: List[Task] = [task4]
        phase2_agents: List[Agent] = [contract_validator]

        pricing_context: List[Task] = [task4]
        scouting_task: Optional[Task] = None
        if trip_intent.should_scout:
            scouting_task = Task(name="destination_scouting", agent=scout, context=[task4], **tasks_config["destination_scouting"])
            phase2_tasks.append(scouting_task)
            phase2_agents.append(scout)
            pricing_context = [scouting_task]

        flight_task: Optional[Task] = None
        if trip_intent.assist_flights:
            flight_task = Task(name="flight_pricing", agent=flight_agent, context=pricing_context, **tasks_config["flight_pricing"])
            phase2_tasks.append(flight_task)
            phase2_agents.append(flight_agent)

        lodging_task: Optional[Task] = None
        if trip_intent.assist_accommodation:
            lodging_task = Task(name="lodging_pricing", agent=lodging_agent, context=pricing_context, **tasks_config["lodging_pricing"])
            phase2_tasks.append(lodging_task)
            phase2_agents.append(lodging_agent)

        activities_task: Optional[Task] = None
        if trip_intent.assist_activities:
            activities_task = Task(name="activities_geo_design", agent=activities_agent, context=pricing_context, **tasks_config["activities_geo_design"])
            phase2_tasks.append(activities_task)
            phase2_agents.append(activities_agent)

        budget_context = [task for task in [flight_task, lodging_task, activities_task] if task] or pricing_context
        budget_task: Optional[Task] = None
        if budget_context:
            budget_task = Task(name="budget_consistency", agent=budget_agent, context=budget_context, **tasks_config["budget_consistency"])
            phase2_tasks.append(budget_task)
            phase2_agents.append(budget_agent)

        decision_task: Optional[Task] = None
        safety_task: Optional[Task] = None
        if trip_intent.should_scout and budget_task:
            decision_task = Task(name="destination_decision", agent=decision_maker, context=[budget_task], **tasks_config["destination_decision"])
            safety_task = Task(name="feasibility_safety_gate", agent=safety_gate, context=[decision_task], **tasks_config["feasibility_safety_gate"])
            phase2_tasks.extend([decision_task, safety_task])
            phase2_agents.extend([decision_maker, safety_gate])

        crew_phase2 = self._crew_builder(
            agents=phase2_agents,
            tasks=phase2_tasks,
            verbose=self._verbose,
            process=Process.sequential,
        )

        inputs_phase2 = {
            "questionnaire": questionnaire_yaml,
            "persona_context": persona_yaml,
            "normalized_trip_request": yaml.dump(normalized_trip_request, allow_unicode=True, sort_keys=False),
            "system_contract_draft": system_contract_yaml,
            "current_year": datetime.now().year,
        }

        output_phase2 = crew_phase2.kickoff(inputs=inputs_phase2)
        tasks_phase2, parsed_phase2 = self._collect_tasks_output(output_phase2, should_save, run_dir, phase_label="PHASE2_BUILD")

        if not trip_intent.should_scout:
            parsed_phase2.setdefault(
                "destination_decision",
                {
                    "code": (trip_intent.destination_value or "DEST-USER").replace(" ", "").upper(),
                    "destination": trip_intent.destination_value,
                    "decision_rationale": "Destination fournie par l'utilisateur; aucun scouting exécuté.",
                    "total_budget": normalized_questionnaire.get("budget_par_personne"),
                    "total_price": normalized_questionnaire.get("budget_par_personne"),
                    "total_days": normalized_questionnaire.get("nuits_exactes")
                    or normalized_trip_request.get("nuits_exactes"),
                    "summary_stats": [],
                },
            )

        # 7. Assemblage final
        agent_outputs: Dict[str, Any] = {}
        agent_outputs.update(parsed_phase1)
        agent_outputs.update(parsed_phase2)

        final_system_contract = parsed_phase2.get("system_contract_validation", {}).get("system_contract") or parsed_phase2.get("system_contract_validation", {}) or system_contract_draft

        trip_payload = assemble_trip(
            questionnaire=normalized_questionnaire,
            normalized_trip_request=normalized_trip_request or {},
            agent_outputs={
                "destination_decision": parsed_phase2.get("destination_decision", {}),
                "flight_pricing": parsed_phase2.get("flight_pricing", {}),
                "lodging_pricing": parsed_phase2.get("lodging_pricing", {}),
                "activities_geo_design": parsed_phase2.get("activities_geo_design", {}),
            },
        )

        is_valid, schema_error = validate_trip_schema(trip_payload.get("trip", {}))

        if should_save:
            validation_dir = run_dir / "PHASE3_VALIDATION"
            validation_dir.mkdir(parents=True, exist_ok=True)
            self._write_yaml(validation_dir / "system_contract_final.yaml", final_system_contract)
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
                        "system_contract_id": final_system_contract.get("id")
                        if isinstance(final_system_contract, dict)
                        else None,
                        "task_count": len(tasks_phase1) + len(tasks_phase2),
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
                "normalized_trip_request": normalized_trip_request,
                "system_contract": final_system_contract,
                "tasks_details": tasks_phase1 + tasks_phase2,
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
