"""Point d'entrée CLI pour exécuter la pipeline CrewAI sans passer par l'API."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

from app.crew_pipeline import run_pipeline_from_payload, travliaq_crew_pipeline
from app.services.persona_inference_service import persona_engine
from app.services.supabase_service import supabase_service

LOGGER = logging.getLogger("app.crew_pipeline.cli")


def _configure_logging(level: str) -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )


def _load_payload_from_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable: {path}")
    with path.open("r", encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except json.JSONDecodeError as exc:  # pragma: no cover - message explicite
            raise ValueError(f"Fichier JSON invalide ({path}): {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Le fichier d'entrée doit contenir un objet JSON.")
    return data


def _build_payload_from_questionnaire(questionnaire_id: str) -> Dict[str, Any]:
    LOGGER.info("📥 Chargement du questionnaire %s", questionnaire_id)
    questionnaire = supabase_service.get_questionnaire_by_id(questionnaire_id)
    if not questionnaire:
        raise RuntimeError(f"Questionnaire introuvable: {questionnaire_id}")

    LOGGER.info("🧠 Inférence du persona de base via PersonaInferenceService")
    inference = persona_engine.infer_persona(questionnaire)
    persona_dict = persona_engine.to_dict(inference)

    return {
        "questionnaire_id": questionnaire_id,
        "questionnaire_data": questionnaire,
        "persona_inference": persona_dict,
    }


def _apply_llm_overrides(*, provider: str | None, model: str | None) -> None:
    """Injecte les surcharges de provider et de modèle dans les variables d'env."""

    if provider:
        os.environ["LLM_PROVIDER"] = provider
        LOGGER.info("⚙️  Provider LLM forcé via la CLI", extra={"provider": provider})

    if model:
        os.environ["MODEL"] = model
        LOGGER.info("⚙️  Modèle LLM forcé via la CLI", extra={"model": model})


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Exécute la pipeline CrewAI pour Travliaq",
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--input-file",
        type=Path,
        help="Payload JSON contenant questionnaire_data et persona_inference",
    )
    source_group.add_argument(
        "--questionnaire-id",
        help="Identifiant du questionnaire à récupérer depuis Supabase",
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Niveau de log (INFO par défaut)",
    )
    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="Afficher aussi la réponse brute renvoyée par CrewAI",
    )

    parser.add_argument(
        "--model",
        help=(
            "Nom du modèle à utiliser (équivalent à la variable d'environnement MODEL). "
            "Permet par exemple de tester `gpt-4.1` ou `gpt-4.1-mini`."
        ),
    )
    parser.add_argument(
        "--llm-provider",
        choices=["openai", "groq", "azure", "azure_openai", "default"],
        help=(
            "Provider LLM à utiliser pour cette exécution uniquement. "
            "Par défaut la valeur provient de LLM_PROVIDER ou de la configuration."
        ),
    )

    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    _configure_logging(args.log_level)

    try:
        if args.input_file:
            payload = _load_payload_from_file(args.input_file)
        else:
            payload = _build_payload_from_questionnaire(args.questionnaire_id)

        _apply_llm_overrides(provider=args.llm_provider, model=args.model)

        LOGGER.info("🚀 Lancement de la pipeline CrewAI (mode CLI)")
        result = run_pipeline_from_payload(payload, pipeline=travliaq_crew_pipeline)

        printable = deepcopy(result)
        if not args.include_raw:
            persona_analysis = printable.get("persona_analysis")
            if isinstance(persona_analysis, dict):
                persona_analysis.pop("raw_response", None)

        print(json.dumps(printable, indent=2, ensure_ascii=False))
        LOGGER.info("✅ Pipeline exécutée avec succès")
        return 0
    except Exception as exc:  # pragma: no cover - garde-fou CLI
        LOGGER.exception("❌ Échec de la pipeline CLI: %s", exc)
        return 1


if __name__ == "__main__":  # pragma: no cover - point d'entrée script
    sys.exit(main())
