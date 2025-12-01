"""Pipeline CrewAI complète (scripts + agents) pour générer le YAML/JSON Trip."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
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
    ) -> None:
        self._llm = llm or self._build_default_llm()
        self._verbose = verbose if verbose is not None else settings.verbose
        self._output_dir = Path(output_dir) if output_dir is not None else Path(settings.crew_output_dir)
        self._config_dir = Path(__file__).resolve().parent / "config"

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

        # 0. Normalisation déterministe (script)
        try:
            normalization = normalize_questionnaire(questionnaire_data)
        except NormalizationError as exc:
            return {
                "run_id": run_id,
                "status": "failed_normalization",
                "error": str(exc),
                "metadata": {"questionnaire_id": self._extract_id(questionnaire_data)},
            }

        normalized_questionnaire = normalization.get("questionnaire", {})

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

        crew_phase1 = Crew(
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
        # ✅ Sauvegarde de TOUS les steps en mode development
        should_save = settings.environment.lower() == "development"
        run_dir = self._output_dir / run_id
        if should_save:
            run_dir.mkdir(parents=True, exist_ok=True)

        tasks_phase1, parsed_phase1 = self._collect_tasks_output(output_phase1, should_save, run_dir, phase_label="PHASE1_ANALYSIS")
        normalized_trip_request = parsed_phase1.get("trip_specifications_design", {}).get("normalized_trip_request")
        if not normalized_trip_request:
            normalized_trip_request = parsed_phase1.get("trip_specifications_design", {})

        # 5. System Contract Draft (script)
        system_contract_draft = build_system_contract(
            questionnaire=normalized_questionnaire,
            normalized_trip_request=normalized_trip_request or {},
            persona_context=persona_inference,
        )
        system_contract_yaml = yaml.dump(system_contract_draft, allow_unicode=True, sort_keys=False)

        # 6. Phase 2 - Validation, scouting, pricing, activités, budget, décision
        task4 = Task(name="system_contract_validation", agent=contract_validator, context=[task1, task2, task3], **tasks_config["system_contract_validation"])
        task5 = Task(name="destination_scouting", agent=scout, context=[task4], **tasks_config["destination_scouting"])
        task6 = Task(name="flight_pricing", agent=flight_agent, context=[task5], **tasks_config["flight_pricing"])
        task7 = Task(name="lodging_pricing", agent=lodging_agent, context=[task5], **tasks_config["lodging_pricing"])
        task8 = Task(name="activities_geo_design", agent=activities_agent, context=[task5], **tasks_config["activities_geo_design"])
        task9 = Task(name="budget_consistency", agent=budget_agent, context=[task6, task7, task8], **tasks_config["budget_consistency"])
        task10 = Task(name="destination_decision", agent=decision_maker, context=[task9], **tasks_config["destination_decision"])
        task11 = Task(name="feasibility_safety_gate", agent=safety_gate, context=[task10], **tasks_config["feasibility_safety_gate"])

        crew_phase2 = Crew(
            agents=[contract_validator, scout, flight_agent, lodging_agent, activities_agent, budget_agent, decision_maker, safety_gate],
            tasks=[task4, task5, task6, task7, task8, task9, task10, task11],
            verbose=self._verbose,
            process=Process.sequential,
        )

        inputs_phase2 = {
            "questionnaire": questionnaire_yaml,
            "persona_context": persona_yaml,
            "normalized_trip_request": yaml.dump(normalized_trip_request, allow_unicode=True, sort_keys=False),
            "system_contract_draft": system_contract_yaml,
        }

        output_phase2 = crew_phase2.kickoff(inputs=inputs_phase2)
        tasks_phase2, parsed_phase2 = self._collect_tasks_output(output_phase2, should_save, run_dir, phase_label="PHASE2_BUILD")

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

        persistence = {
            "saved": False,
            "table": settings.trip_recommendations_table,
            "schema_valid": is_valid,
        }

        trip_core = trip_payload.get("trip")
        if trip_core:
            try:
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

    def _build_default_llm(self) -> LLM:
        """Construit le LLM en fonction de la configuration (OpenAI, Groq, Azure)."""
        model = settings.model_name.lower()
        
        # Configuration Azure
        if model.startswith("azure/"):
            return LLM(
                model=settings.model_name,
                api_key=settings.azure_openai_api_key,
                base_url=settings.azure_openai_endpoint,
                api_version=settings.azure_openai_api_version,
                temperature=settings.temperature,
                timeout=120,  # 2 minutes max par appel
                max_retries=3  # 3 tentatives en cas d'échec
            )
            
        # Configuration Groq
        if model.startswith("groq/"):
            return LLM(
                model=settings.model_name,
                api_key=settings.groq_api_key,
                temperature=settings.temperature,
                timeout=120,
                max_retries=3
            )
            
        # Par défaut : OpenAI (ou compatible)
        return LLM(
            model=settings.model_name,
            api_key=settings.openai_api_key,
            temperature=settings.temperature,
            timeout=120,  # 2 minutes max par appel
            max_retries=3  # 3 tentatives automatiques
        )

# Instance globale
travliaq_crew_pipeline = CrewPipeline()

def run_pipeline_with_inputs(**kwargs):
    return travliaq_crew_pipeline.run(**kwargs)
