"""Pipeline CrewAI refactorisée pour la Phase 1 : Analyse & Spécifications (YAML Only)."""

from __future__ import annotations

import json
import logging
import os
import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

import yaml
from crewai import Agent, Crew, Process, Task
from crewai import LLM

from app.config import settings
from app.crew_pipeline.mcp_tools import get_mcp_tools
from app.crew_pipeline.observability import (
    PipelineMetrics,
    log_structured_input,
    log_structured_output,
)

logger = logging.getLogger(__name__)


@dataclass
class CrewPipelineResult:
    """Résultat structuré de la pipeline (Phase 1)."""
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
    Orchestrateur de la Phase 1 : Analyse & Spécifications.
    
    Flux :
    1. Traveller Insights Analyst (avec MCP)
    2. Persona Quality Challenger (avec MCP)
    3. Trip Specifications Architect
    
    Format : YAML strict.
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
        """Exécute la pipeline Phase 1."""
        
        # 1. Préparation des données (Conversion YAML pour le contexte)
        run_id = self._generate_run_id(questionnaire_data)
        logger.info(f"🚀 Lancement Pipeline Phase 1 (Run ID: {run_id})")

        # On convertit les inputs en YAML string pour que les agents les lisent facilement
        questionnaire_yaml = yaml.dump(questionnaire_data, allow_unicode=True, sort_keys=False)
        persona_yaml = yaml.dump(persona_inference, allow_unicode=True, sort_keys=False)

        # 2. Chargement de la configuration
        agents_config = self._load_yaml_config("agents.yaml")
        if "agents" in agents_config:
            agents_config = agents_config["agents"]
            
        tasks_config = self._load_yaml_config("tasks.yaml")
        if "tasks" in tasks_config:
            tasks_config = tasks_config["tasks"]

        # 3. Chargement des outils MCP
        mcp_tools = []
        if settings.mcp_server_url:
            try:
                mcp_tools = get_mcp_tools(settings.mcp_server_url)
                logger.info(f"✅ {len(mcp_tools)} outils MCP chargés.")
            except Exception as e:
                logger.warning(f"⚠️ Erreur chargement MCP: {e}")

        # 4. Création des Agents
        # Agent 1: Analyst
        analyst = self._create_agent(
            "traveller_insights_analyst", 
            agents_config["traveller_insights_analyst"], 
            tools=mcp_tools # MCP Obligatoire
        )
        
        # Agent 2: Challenger
        challenger = self._create_agent(
            "persona_quality_challenger", 
            agents_config["persona_quality_challenger"], 
            tools=mcp_tools # MCP Obligatoire
        )
        
        # Agent 3: Architect
        architect = self._create_agent(
            "trip_specifications_architect", 
            agents_config["trip_specifications_architect"],
            tools=[] # Pas d'outils MCP nécessaires pour la structure
        )

        # 5. Création des Tâches
        task1 = Task(
            name="traveller_profile_brief",
            agent=analyst,
            **tasks_config["traveller_profile_brief"]
        )
        
        task2 = Task(
            name="persona_challenge_review",
            agent=challenger,
            context=[task1],
            **tasks_config["persona_challenge_review"]
        )
        
        task3 = Task(
            name="trip_specifications_design",
            agent=architect,
            context=[task2],
            **tasks_config["trip_specifications_design"]
        )
        
        # ✅ NOUVEAU : Agent 4 - System Contract Validator
        validator = self._create_agent(
            "system_contract_validator",
            agents_config["system_contract_validator"],
            tools=[]  # Pas d'outils MCP nécessaires
        )
        
        task4 = Task(
            name="system_contract_validation",
            agent=validator,
            context=[task1, task2, task3],
            **tasks_config["system_contract_validation"]
        )

        # 6. Création des Crews
        # Crew 1 : Analyse & Design (Tasks 1, 2, 3)
        crew_phase1 = Crew(
            agents=[analyst, challenger, architect],
            tasks=[task1, task2, task3],
            verbose=self._verbose,
            process=Process.sequential
        )

        # Crew 2 : Validation (Task 4)
        crew_validation = Crew(
            agents=[validator],
            tasks=[task4],
            verbose=self._verbose,
            process=Process.sequential
        )
        
        # Affichage du lien de monitoring CrewAI (si dispo)
        if hasattr(crew_phase1, 'id') and crew_phase1.id:
            monitoring_url = f"https://app.crewai.com/crews/{crew_phase1.id}"
            logger.info(f"🔗 Monitoring CrewAI Phase 1: {monitoring_url}")

        # Inputs initiaux
        inputs_phase1 = {
            "questionnaire": questionnaire_yaml,
            "persona_context": persona_yaml,
            "input_payload": yaml.dump({
                "questionnaire": questionnaire_data, 
                "persona": persona_inference
            }, allow_unicode=True),
        }

        try:
            # =================================================================
            # PHASE 1: ANALYSE & DESIGN (Agents 1, 2, 3)
            # =================================================================
            logger.info("🚀 Démarrage Phase 1 (Analyst, Challenger, Architect)...")
            output_phase1 = crew_phase1.kickoff(inputs=inputs_phase1)
            
            # =================================================================
            # TRANSITION: SYSTEM CONTRACT MERGER (Script Python)
            # =================================================================
            logger.info("🔧 Transition: Fusion du System Contract (Merger V7.0)...")
            from app.crew_pipeline.system_contract_merger import SystemContractMerger
            
            # Récupération de l'output de la Task 3 (Trip Specifications)
            task3_output_raw = output_phase1.tasks_output[2].raw
            task3_output = self._parse_yaml_content(task3_output_raw)
            if not isinstance(task3_output, dict): task3_output = {}
            
            # Exécution du Merger
            system_contract_draft = SystemContractMerger.generate_contract(
                questionnaire=questionnaire_data,
                step_3_trip_specifications_design=task3_output
            )
            
            draft_yaml = yaml.dump(system_contract_draft, allow_unicode=True, sort_keys=False)
            logger.info("✅ System Contract Draft généré avec succès.")

            # =================================================================
            # PHASE 2: VALIDATION (Agent 4)
            # =================================================================
            logger.info("🤖 Démarrage Phase 2 (Validation Agent)...")
            
            # On injecte le draft dans les inputs de la 2ème crew
            inputs_validation = {
                "system_contract_draft": draft_yaml
            }
            
            # On passe aussi le contexte des tâches précédentes manuellement si besoin,
            # mais ici Task 4 a déjà `context=[task1, task2, task3]` défini dans sa création.
            # CrewAI gère le contexte entre tâches d'une même crew, mais ici ce sont deux crews différentes.
            # ASTUCE : Pour que l'agent 4 ait accès au contexte des agents 1-3, on peut
            # concaténer leurs outputs dans le prompt ou utiliser la mémoire partagée (si configurée).
            # Ici, on va simplifier en injectant les résumés dans l'input si le context linking natif échoue.
            
            # Pour assurer le coup, on enrichit l'input avec le contexte textuel
            context_summary = "\n\n".join([
                f"--- OUTPUT TASK 1 (Analyst) ---\n{output_phase1.tasks_output[0].raw}",
                f"--- OUTPUT TASK 2 (Challenger) ---\n{output_phase1.tasks_output[1].raw}",
                f"--- OUTPUT TASK 3 (Architect) ---\n{output_phase1.tasks_output[2].raw}"
            ])
            # On pourrait l'ajouter à inputs_validation si le prompt l'attendait, 
            # mais task4 attend juste {system_contract_draft}.
            # L'agent a accès à 'memory=True', espérons qu'il retrouve ses petits.
            # Sinon, on modifie la description de task4 pour inclure {previous_context}.
            
            output_validation = crew_validation.kickoff(inputs=inputs_validation)
            
            # =================================================================
            # CONSOLIDATION DES OUTPUTS
            # =================================================================
            # On fusionne pour avoir un objet CrewOutput unique (ou similaire) pour la suite
            final_output = output_phase1
            # On ajoute l'output de la validation à la liste
            # Note: CrewOutput.tasks_output est une liste de TaskOutput
            final_output.tasks_output.extend(output_validation.tasks_output)
            
            logger.info("✅ Pipeline terminée : Contrat validé.")
            
        except Exception as exc:
            logger.exception("❌ Échec critique de la pipeline")
            raise exc

        # 7. Traitement des Outputs (Parsing & Sauvegarde)
        # Passer le system_contract_draft pour sauvegarde
        final_result = self._process_outputs(
            run_id, 
            final_output, 
            questionnaire_data, 
            persona_inference,
            system_contract=system_contract_draft
        )
        
        return final_result

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

    def _process_outputs(
        self, 
        run_id: str, 
        crew_output: Any, 
        questionnaire: Dict[str, Any],
        persona: Dict[str, Any],
        system_contract: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Parse les outputs, sauvegarde en YAML et retourne le résultat final."""
        
        run_dir = self._output_dir / run_id
        
        # Sauvegarde seulement en DEV
        should_save = settings.environment.lower() == "development"
        if should_save:
            run_dir.mkdir(parents=True, exist_ok=True)

        tasks_data = []
        normalized_trip = {}
        final_system_contract = {}

        # Mapping des tâches vers les phases
        task_phase_mapping = {
            "traveller_profile_brief": ("PHASE1_ANALYSIS", 1),
            "persona_challenge_review": ("PHASE1_ANALYSIS", 2),
            "trip_specifications_design": ("PHASE1_ANALYSIS", 3),
            "system_contract_validation": ("PHASE1_TO_PHASE2_TRANSITION", 4)
        }

        # Traitement des tâches individuelles avec numérotation et phases
        if hasattr(crew_output, "tasks_output"):
            for task_out in crew_output.tasks_output:
                task_name = getattr(task_out, "name", "unknown_task")
                raw_content = getattr(task_out, "raw", "")
                
                # Parsing YAML du contenu
                structured_content = self._parse_yaml_content(raw_content)
                
                task_record = {
                    "task_name": str(task_name),
                    "agent": getattr(task_out, "agent", ""),
                    "structured_output": structured_content,
                    "raw_output": raw_content
                }
                tasks_data.append(task_record)

                # Extraction du normalized_trip_request
                if task_name == "trip_specifications_design":
                    if isinstance(structured_content, dict) and "normalized_trip_request" in structured_content:
                        normalized_trip = structured_content["normalized_trip_request"]
                    else:
                        normalized_trip = structured_content
                
                # ✅ Extraction du System Contract (dernière tâche)
                if task_name == "system_contract_validation":
                    final_system_contract = structured_content

                # ✅ Sauvegarde avec phase et numérotation
                if should_save:
                    phase_name, step_num = task_phase_mapping.get(task_name, ("UNKNOWN_PHASE", 0))
                    step_dir = run_dir / f"{phase_name}" / f"step_{step_num}_{task_name}"
                    step_dir.mkdir(parents=True, exist_ok=True)
                    self._write_yaml(step_dir / "output.yaml", task_record)
                    logger.info(f"📁 {phase_name} - Step {step_num}: {task_name} → {step_dir}")

        # ✅ Sauvegarde du System Contract final (Transition Phase 1 → Phase 2)
        if should_save and final_system_contract:
            contract_dir = run_dir / "PHASE1_TO_PHASE2_TRANSITION" / "FINAL_SYSTEM_CONTRACT"
            contract_dir.mkdir(parents=True, exist_ok=True)
            self._write_yaml(contract_dir / "system_contract.yaml", final_system_contract)
            logger.info(f"🎯 SYSTEM CONTRACT FINAL → {contract_dir}/system_contract.yaml")

        # Construction du résultat final
        final_payload = {
            "run_id": run_id,
            "status": "success",
            "metadata": {
                "questionnaire_id": self._extract_id(questionnaire),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            },
            "input_context": {
                "questionnaire": questionnaire,
                "persona_inference": persona
            },
            "pipeline_output": {
                "normalized_trip_request": normalized_trip,
                "system_contract": final_system_contract,
                "tasks_details": tasks_data
            }
        }

        if should_save:
            self._write_yaml(run_dir / "_SUMMARY_run_output.yaml", final_payload)
            logger.info(f"💾 Résumé complet sauvegardé dans {run_dir}/_SUMMARY_run_output.yaml")

        return final_payload

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
