"""Pipeline CrewAI pour l'enrichissement des questionnaires voyage."""

from __future__ import annotations

import json
import logging
import os
import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from crewai import Agent, Crew, Process, Task
from crewai import LLM

import yaml

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class CrewPipelineResult:
    """Résultat structuré renvoyé par l'orchestration CrewAI."""

    persona_summary: str = ""
    pros: List[str] = field(default_factory=list)
    cons: List[str] = field(default_factory=list)
    critical_needs: List[str] = field(default_factory=list)
    non_critical_preferences: List[str] = field(default_factory=list)
    user_goals: List[str] = field(default_factory=list)
    narrative: str = ""
    analysis_notes: str = ""
    challenge_summary: str = ""
    challenge_actions: List[str] = field(default_factory=list)
    raw_response: str = ""
    normalized_trip_request: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Transforme le résultat en dictionnaire JSON sérialisable."""

        return {
            "persona_summary": self.persona_summary,
            "pros": self.pros,
            "cons": self.cons,
            "critical_needs": self.critical_needs,
            "non_critical_preferences": self.non_critical_preferences,
            "user_goals": self.user_goals,
            "narrative": self.narrative,
            "analysis_notes": self.analysis_notes,
            "challenge_summary": self.challenge_summary,
            "challenge_actions": self.challenge_actions,
            "raw_response": self.raw_response,
            "normalized_trip_request": self.normalized_trip_request,
        }


def _default_result_from_raw(raw: str, note: str) -> CrewPipelineResult:
    """Crée un résultat par défaut lorsqu'on ne peut pas parser le JSON."""

    cleaned = raw.strip()
    return CrewPipelineResult(
        persona_summary="Analyse non structurée",
        narrative=cleaned,
        analysis_notes=note,
        raw_response=raw,
    )


_PLACEHOLDER_TOKENS = {
    "your_key_here",
    "your-api-key",
    "your_api_key",
    "changeme",
    "replace_me",
    "todo",
    "set_me",
}


def _is_placeholder_secret(value: Optional[str]) -> bool:
    """Indique si une valeur ressemble à un secret de substitution."""

    if value is None:
        return True

    normalized = value.strip().lower()
    if not normalized:
        return True

    if normalized in _PLACEHOLDER_TOKENS:
        return True

    # Les exemples classiques dans les fichiers `.env` contiennent souvent
    # "your" + "key" + "here" avec diverses ponctuations.
    if "your" in normalized and "key" in normalized and "here" in normalized:
        return True

    return False


def _pick_first_secret(*candidates: Optional[str]) -> Optional[str]:
    """Retourne le premier secret non vide qui n'est pas un placeholder."""

    for candidate in candidates:
        if _is_placeholder_secret(candidate):
            continue
        return candidate
    return None


def _detect_llm_provider() -> str:
    """Détermine le provider LLM à utiliser en priorité."""

    provider = os.getenv("LLM_PROVIDER", settings.model_provider or "openai")
    return provider.lower()


def _slugify_filename(value: str) -> str:
    """Génère un nom de fichier sûr à partir d'un libellé de tâche."""

    slug = re.sub(r"[^0-9a-zA-Z]+", "_", value.strip().lower())
    slug = slug.strip("_")
    return slug or "task"


def _write_json_file(path: Path, data: Any) -> None:
    """Persist a JSON payload to disk, logging any failure."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:  # pragma: no cover - dépend du FS
        logger.warning(
            "Impossible d'enregistrer un fichier de sortie CrewAI",
            extra={"path": str(path), "error": str(exc)},
        )


_CONFIG_DIR = Path(__file__).resolve().parent / "config"
_CONFIG_CACHE: Dict[str, Dict[str, Any]] = {}

_CONFIG_FILENAMES = {
    "agents": "agents.yaml",
    "tasks": "tasks.yaml",
    "crew": "crew.yaml",
}

def _load_yaml_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Configuration CrewAI manquante: {path}")

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Configuration YAML invalide pour {path}")

    return data


def _load_pipeline_blueprint() -> Dict[str, Dict[str, Any]]:
    cache_key = "travliaq"
    if cache_key not in _CONFIG_CACHE:
        blueprint: Dict[str, Dict[str, Any]] = {}
        for section, filename in _CONFIG_FILENAMES.items():
            data = _load_yaml_file(_CONFIG_DIR / filename)
            # Autorise un format avec ou sans clé racine.
            blueprint[section] = data.get(section, data)
        _CONFIG_CACHE[cache_key] = blueprint
    return _CONFIG_CACHE[cache_key]


def _build_default_llm() -> LLM:
    """Construit une instance LLM compatible CrewAI selon la configuration."""

    provider = _detect_llm_provider()
    model_name = (
        os.getenv("MODEL")
        or settings.model_name
        or os.getenv("OPENAI_MODEL")
        or "gpt-4o-mini"
    )
    base_kwargs: Dict[str, Any] = {
        "model": model_name,
        "temperature": settings.temperature,
    }

    if provider in {"openai", "default"}:
        api_key = _pick_first_secret(
            getattr(settings, "openai_api_key", None),
            os.getenv("OPENAI_API_KEY"),
        )
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY requis pour exécuter la pipeline CrewAI"
            )
        base_kwargs["api_key"] = api_key
    elif provider == "groq":
        api_key = _pick_first_secret(
            getattr(settings, "groq_api_key", None),
            os.getenv("GROQ_API_KEY"),
        )
        if not api_key:
            raise RuntimeError("GROQ_API_KEY requis pour le provider Groq")
        base_kwargs["api_key"] = api_key
    elif provider in {"azure", "azure_openai"}:
        api_key = _pick_first_secret(
            getattr(settings, "azure_openai_api_key", None),
            os.getenv("AZURE_OPENAI_API_KEY"),
        )
        endpoint = settings.azure_openai_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        deployment = (
            settings.azure_openai_deployment or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        )
        api_version = (
            settings.azure_openai_api_version or os.getenv("AZURE_OPENAI_API_VERSION")
        )
        if not all([api_key, endpoint, deployment]):
            raise RuntimeError(
                "Configuration Azure OpenAI incomplète (clé, endpoint, deployment)"
            )
        base_kwargs.update(
            {
                "api_key": api_key,
                "base_url": endpoint.rstrip("/"),
                "model": deployment,
            }
        )
        if api_version:
            base_kwargs["api_version"] = api_version
    else:
        raise RuntimeError(f"Provider LLM non supporté: {provider}")

    logger.debug(
        "Initialisation LLM CrewAI", extra={"provider": provider, "model": model_name}
    )
    return LLM(**base_kwargs)


def _create_agent(
    *,
    name: str,
    config: Dict[str, Any],
    llm_instance: LLM,
    agent_verbose: bool,
) -> Agent:
    agent_kwargs = dict(config)
    agent_kwargs.setdefault("verbose", agent_verbose)
    if settings.max_iter is not None and "max_iter" not in agent_kwargs:
        agent_kwargs["max_iter"] = settings.max_iter
    if settings.max_rpm is not None and "max_rpm" not in agent_kwargs:
        agent_kwargs["max_rpm"] = settings.max_rpm

    # Force l'utilisation du LLM calculé dynamiquement.
    agent_kwargs["llm"] = llm_instance

    try:
        return Agent(**agent_kwargs)
    except TypeError as exc:  # pragma: no cover - garde-fou sur configuration
        raise TypeError(f"Configuration agent invalide pour '{name}': {exc}")


def _resolve_process(value: Any) -> Process:
    if isinstance(value, Process):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if hasattr(Process, normalized):
            return getattr(Process, normalized)
    if value is None:
        return Process.sequential
    raise ValueError(f"Process CrewAI inconnu: {value}")


def build_travliaq_crew(
    *, llm: Optional[LLM] = None, verbose: Optional[bool] = None
) -> Crew:
    """Construit la Crew utilisée pour enrichir un questionnaire."""

    llm_instance = llm or _build_default_llm()
    agent_verbose = verbose if verbose is not None else settings.verbose

    blueprint = _load_pipeline_blueprint()
    agents_config = blueprint.get("agents", {})
    tasks_config = blueprint.get("tasks", {})
    crew_config = blueprint.get("crew", {})

    if not agents_config:
        raise ValueError("Aucun agent défini dans la configuration CrewAI")
    if not tasks_config:
        raise ValueError("Aucune tâche définie dans la configuration CrewAI")

    agents: Dict[str, Agent] = {}
    for agent_name, agent_definition in agents_config.items():
        agents[agent_name] = _create_agent(
            name=agent_name,
            config=agent_definition,
            llm_instance=llm_instance,
            agent_verbose=agent_verbose,
        )

    tasks: Dict[str, Task] = {}
    for task_name, task_definition in tasks_config.items():
        task_kwargs = dict(task_definition)
        agent_key = task_kwargs.pop("agent", None)
        if agent_key is None:
            raise ValueError(f"Tâche '{task_name}' sans agent associé")
        if agent_key not in agents:
            raise ValueError(
                f"Tâche '{task_name}' fait référence à l'agent inconnu '{agent_key}'"
            )

        # Les contextes peuvent référencer d'autres tâches. On résout plus tard.
        context_refs = task_kwargs.pop("context", None)

        try:
            task = Task(agent=agents[agent_key], **task_kwargs)
        except TypeError as exc:  # pragma: no cover - configuration invalide
            raise TypeError(f"Configuration tâche invalide pour '{task_name}': {exc}")

        if context_refs:
            # Résout les contextes en objets Task existants.
            resolved_context = []
            for ref in context_refs:
                if ref not in tasks:
                    raise ValueError(
                        f"La tâche '{task_name}' référence un contexte inconnu '{ref}'"
                    )
                resolved_context.append(tasks[ref])
            task.context = resolved_context

        tasks[task_name] = task

    crew_kwargs = dict(crew_config)
    agent_refs = crew_kwargs.pop("agents", list(agents.keys()))
    task_refs = crew_kwargs.pop("tasks", list(tasks.keys()))

    crew_agents = []
    for ref in agent_refs:
        if ref not in agents:
            raise ValueError(f"Agent '{ref}' absent de la configuration")
        crew_agents.append(agents[ref])

    crew_tasks = []
    for ref in task_refs:
        if ref not in tasks:
            raise ValueError(f"Tâche '{ref}' absente de la configuration")
        crew_tasks.append(tasks[ref])

    process_value = crew_kwargs.pop("process", Process.sequential)
    crew_kwargs["process"] = _resolve_process(process_value)

    crew_kwargs.setdefault("verbose", agent_verbose)

    return Crew(agents=crew_agents, tasks=crew_tasks, **crew_kwargs)


class CrewPipeline:
    """Pipeline orchestrant l'appel à CrewAI pour enrichir les données voyage."""

    def __init__(
        self,
        crew_builder: Callable[..., Crew] = build_travliaq_crew,
        *,
        llm: Optional[LLM] = None,
        verbose: Optional[bool] = None,
        output_dir: Optional[Path] = None,
    ) -> None:
        self._crew_builder = crew_builder
        self._crew: Optional[Crew] = None
        self._llm = llm
        self._verbose = verbose
        self._output_dir = Path(output_dir) if output_dir is not None else Path(
            settings.crew_output_dir
        )

    def _ensure_crew(self) -> Crew:
        if self._crew is None:
            builder_kwargs: Dict[str, Any] = {}
            if self._llm is not None:
                builder_kwargs["llm"] = self._llm
            if self._verbose is not None:
                builder_kwargs["verbose"] = self._verbose

            try:
                self._crew = self._crew_builder(**builder_kwargs)
            except TypeError:
                # Certains builders de tests n'acceptent pas de kwargs.
                self._crew = self._crew_builder()
        return self._crew

    def run(
        self,
        *,
        questionnaire_data: Dict[str, Any],
        persona_inference: Dict[str, Any],
        payload_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Exécute la pipeline CrewAI et retourne un dictionnaire prêt pour l'API."""

        crew = self._ensure_crew()
        logger.info("🚀 Lancement de la pipeline CrewAI pour l'analyse voyage")

        base_payload: Dict[str, Any] = {
            "questionnaire_data": deepcopy(questionnaire_data),
            "persona_inference": deepcopy(persona_inference),
        }
        if payload_metadata:
            for key, value in payload_metadata.items():
                if key in {"questionnaire_data", "persona_inference"}:
                    continue
                base_payload[key] = deepcopy(value)

        try:
            output = crew.kickoff(
                inputs={
                    "questionnaire": questionnaire_data,
                    "persona_context": persona_inference,
                    "input_payload": base_payload,
                }
            )
        except Exception as exc:
            logger.exception("Échec lors de l'exécution de CrewAI: %s", exc)
            raise

        result = self._parse_output(output)
        run_id = self._generate_run_id(base_payload)
        enriched = self._compose_enriched_payload(
            run_id=run_id,
            base_payload=base_payload,
            analysis=result,
        )
        self._persist_run_outputs(run_id, output, enriched)

        logger.info("✅ Analyse CrewAI générée avec succès", extra={"run_id": run_id})
        return enriched

    def _parse_output(self, output: Any) -> CrewPipelineResult:
        """Normalise le résultat renvoyé par CrewAI en CrewPipelineResult."""

        if output is None:
            return _default_result_from_raw(
                "",
                "La sortie de CrewAI est vide.",
            )

        raw_candidate: Any = None

        # Crew 0.70 renvoie un objet CrewOutput avec .raw et .json_dict
        if hasattr(output, "json_dict") and getattr(output, "json_dict"):
            json_candidate = getattr(output, "json_dict")
            if isinstance(json_candidate, dict):
                return self._result_from_dict(json_candidate, raw=str(getattr(output, "raw", "")))

        if hasattr(output, "raw"):
            raw_candidate = getattr(output, "raw")

        if isinstance(output, dict):
            return self._result_from_dict(output, raw=json.dumps(output, ensure_ascii=False))

        if isinstance(output, str):
            raw_candidate = output

        if raw_candidate is None:
            raw_candidate = str(output)

        try:
            parsed_payload = self._extract_structured_payload(raw_candidate)
            return self._result_from_dict(parsed_payload, raw=raw_candidate)
        except ValueError:
            note = (
                "La sortie de l'agent ne respecte pas le format structuré (JSON ou YAML) attendu. "
                "Voir raw_response pour l'analyse brute."
            )
            return _default_result_from_raw(str(raw_candidate), note)

    @staticmethod
    def _extract_structured_payload(raw: str) -> Dict[str, Any]:
        """Tente d'extraire un dictionnaire JSON ou YAML depuis la sortie."""

        text = raw.strip()
        if not text:
            raise ValueError("empty")

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                snippet = text[start : end + 1]
                try:
                    return json.loads(snippet)
                except json.JSONDecodeError:
                    pass

        try:
            yaml_data = yaml.safe_load(text)
        except yaml.YAMLError as exc:  # pragma: no cover - dépend du contenu
            raise ValueError("invalid structured payload") from exc

        if isinstance(yaml_data, dict):
            return yaml_data

        raise ValueError("invalid structured payload")

    def _result_from_dict(
        self, data: Dict[str, Any], *, raw: Optional[str] = None
    ) -> CrewPipelineResult:
        """Normalise un dictionnaire issu de CrewAI."""

        def _as_list(value: Any) -> List[str]:
            if isinstance(value, list):
                return [str(item) for item in value]
            if value is None:
                return []
            return [str(value)]

        result = CrewPipelineResult(
            persona_summary=str(data.get("persona_summary", "")).strip(),
            pros=_as_list(data.get("pros")),
            cons=_as_list(data.get("cons")),
            critical_needs=_as_list(data.get("critical_needs")),
            non_critical_preferences=_as_list(data.get("non_critical_preferences")),
            user_goals=_as_list(data.get("user_goals")),
            narrative=str(data.get("narrative", "")).strip(),
            analysis_notes=str(data.get("analysis_notes", "")).strip(),
            challenge_summary=str(data.get("challenge_summary", "")).strip(),
            challenge_actions=_as_list(data.get("challenge_actions")),
            raw_response=raw or json.dumps(data, ensure_ascii=False),
        )

        normalized_trip = data.get("normalized_trip_request")
        if isinstance(normalized_trip, dict):
            result.normalized_trip_request = normalized_trip

        return result


    @staticmethod
    def _extract_questionnaire_id(payload: Dict[str, Any]) -> str:
        """Tente de retrouver l'identifiant du questionnaire dans les données."""

        candidate = payload.get("questionnaire_id")
        if candidate:
            return str(candidate)

        questionnaire = payload.get("questionnaire_data") or {}
        if isinstance(questionnaire, dict):
            for key in ("id", "questionnaire_id"):
                value = questionnaire.get(key)
                if value:
                    return str(value)

        persona = payload.get("persona_inference") or {}
        if isinstance(persona, dict):
            for key in ("questionnaire_id", "id"):
                value = persona.get(key)
                if value:
                    return str(value)

        return ""

    def _generate_run_id(self, payload: Dict[str, Any]) -> str:
        """Crée un identifiant de run unique et lisible."""

        questionnaire_id = self._extract_questionnaire_id(payload)
        suffix = uuid4().hex[:8]
        if questionnaire_id:
            return f"{_slugify_filename(questionnaire_id)}-{suffix}"
        return f"run-{suffix}"

    def _compose_enriched_payload(
        self,
        *,
        run_id: str,
        base_payload: Dict[str, Any],
        analysis: CrewPipelineResult,
    ) -> Dict[str, Any]:
        """Assemble le JSON final mêlant input et analyse."""

        enriched = deepcopy(base_payload)
        enriched.setdefault("status", "ok")
        enriched["run_id"] = run_id
        persona_analysis = analysis.to_dict()
        enriched["persona_analysis"] = persona_analysis

        if analysis.normalized_trip_request:
            enriched["normalized_trip_request"] = analysis.normalized_trip_request

        questionnaire_id = self._extract_questionnaire_id(enriched)
        if questionnaire_id:
            enriched["questionnaire_id"] = questionnaire_id

        return enriched

    def _persist_run_outputs(
        self,
        run_id: str,
        output: Any,
        final_payload: Dict[str, Any],
    ) -> None:
        """Enregistre les sorties de la run (finale + par tâche)."""

        run_dir = self._output_dir / run_id
        _write_json_file(run_dir / "run_output.json", final_payload)

        task_outputs = getattr(output, "tasks_output", None)
        if not task_outputs:
            return

        tasks_dir = run_dir / "tasks"
        for index, task_output in enumerate(task_outputs, start=1):
            task_name = getattr(task_output, "name", None) or f"task_{index}"
            file_name = f"{_slugify_filename(str(task_name)) or f'task_{index}'}" + ".json"

            task_payload: Dict[str, Any] = {
                "task_name": str(task_name),
                "agent": getattr(task_output, "agent", ""),
                "description": getattr(task_output, "description", ""),
                "raw_output": getattr(task_output, "raw", ""),
            }

            expected = getattr(task_output, "expected_output", None)
            if expected:
                task_payload["expected_output"] = expected

            json_dict = getattr(task_output, "json_dict", None)
            if json_dict:
                task_payload["json_output"] = json_dict

            _write_json_file(tasks_dir / file_name, task_payload)

# Instance globale réutilisée par l'API et les scripts CLI
travliaq_crew_pipeline = CrewPipeline()


def run_pipeline_with_inputs(
    *,
    questionnaire_data: Dict[str, Any],
    persona_inference: Dict[str, Any],
    pipeline: Optional[CrewPipeline] = None,
    payload_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Exécute la pipeline à partir de données déjà préparées."""

    runner = pipeline or travliaq_crew_pipeline
    return runner.run(
        questionnaire_data=questionnaire_data,
        persona_inference=persona_inference,
        payload_metadata=payload_metadata,
    )


def run_pipeline_from_payload(
    payload: Dict[str, Any], *, pipeline: Optional[CrewPipeline] = None
) -> Dict[str, Any]:
    """Exécute la pipeline à partir d'un payload complet (questionnaire + persona)."""

    if "questionnaire_data" not in payload:
        raise ValueError("Payload incomplet: 'questionnaire_data' manquant")
    if "persona_inference" not in payload:
        raise ValueError("Payload incomplet: 'persona_inference' manquant")

    metadata = {
        key: value
        for key, value in payload.items()
        if key not in {"questionnaire_data", "persona_inference"}
    }

    return run_pipeline_with_inputs(
        questionnaire_data=payload["questionnaire_data"],
        persona_inference=payload["persona_inference"],
        pipeline=pipeline,
        payload_metadata=metadata,
    )

