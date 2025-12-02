"""Configuration centralisée du logging pour la pipeline CrewAI.

Ce module configure un système de logs qui :
- Écrase le fichier logLastPipeline.txt à chaque exécution
- Enregistre tous les logs de tous les modules
- Maintient aussi une sortie console pour le développement
"""

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_pipeline_logging(
    log_file: Optional[Path] = None,
    level: int = logging.INFO,
    console_output: bool = True,
) -> None:
    """
    Configure le système de logging pour la pipeline.

    Args:
        log_file: Chemin du fichier de log (défaut: logLastPipeline.txt à la racine)
        level: Niveau de log (défaut: INFO)
        console_output: Si True, affiche aussi les logs en console (défaut: True)
    """
    # Déterminer le chemin du fichier de log
    if log_file is None:
        # Remonter à la racine du projet (2 niveaux au-dessus de ce fichier)
        project_root = Path(__file__).resolve().parent.parent.parent
        log_file = project_root / "logLastPipeline.txt"

    # S'assurer que le dossier parent existe
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Formatter commun pour console et fichier
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Handler fichier : MODE 'w' = ÉCRASEMENT à chaque exécution
    file_handler = logging.FileHandler(
        log_file,
        mode="w",  # 'w' = overwrite, 'a' = append
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    # Handler console (optionnel)
    handlers = [file_handler]
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        handlers.append(console_handler)

    # Configurer le logger racine pour capturer TOUS les logs
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Supprimer les handlers existants pour éviter les doublons
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Ajouter les nouveaux handlers
    for handler in handlers:
        root_logger.addHandler(handler)

    # Réduire la verbosité de certaines bibliothèques externes
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # Log initial pour confirmer la configuration
    logging.info("=" * 80)
    logging.info("TRAVLIAQ PIPELINE - LOGS INITIALIZED")
    logging.info(f"Log file: {log_file}")
    logging.info(f"Log level: {logging.getLevelName(level)}")
    logging.info(f"Console output: {'Enabled' if console_output else 'Disabled'}")
    logging.info("=" * 80)


def get_logger(name: str) -> logging.Logger:
    """
    Récupère un logger nommé (helper pour simplifier l'usage).

    Args:
        name: Nom du logger (généralement __name__)

    Returns:
        Logger configuré
    """
    return logging.getLogger(name)
