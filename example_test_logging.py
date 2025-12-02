"""Exemple simple pour tester le système de logging avec la pipeline."""

import json
import logging
from pathlib import Path

from app.crew_pipeline.logging_config import setup_pipeline_logging

# Configurer le logging manuellement pour cet exemple
setup_pipeline_logging(level=logging.INFO, console_output=True)

logger = logging.getLogger(__name__)

logger.info("=" * 80)
logger.info("EXEMPLE DE TEST DU SYSTÈME DE LOGGING")
logger.info("=" * 80)

# Simuler des logs de différents modules
logger_pipeline = logging.getLogger("app.crew_pipeline.pipeline")
logger_mcp = logging.getLogger("app.crew_pipeline.mcp_tools")
logger_scripts = logging.getLogger("app.crew_pipeline.scripts")

logger_pipeline.info("Démarrage de la pipeline...")
logger_pipeline.info("Chargement du questionnaire...")

logger_scripts.info("Normalisation du questionnaire en cours...")
logger_scripts.warning("Date au format européen détectée, conversion en cours...")

logger_mcp.info("Connexion au serveur MCP...")
logger_mcp.info("Outils MCP chargés: flights.prices, booking.search, places.overview")

logger_pipeline.info("Phase 1 - Analyse du persona...")
logger_pipeline.info("Phase 2 - Build des recommandations...")

logger_mcp.warning("Appel API flights.prices avec dates validées")
logger_mcp.info("Résultats reçus: 850€ BRU -> DPS")

logger_pipeline.info("Pipeline terminée avec succès")
logger_pipeline.info("Résultats sauvegardés dans output/")

logger.info("=" * 80)
logger.info("FIN DE L'EXEMPLE")
logger.info("=" * 80)

# Vérifier que le fichier a été créé
log_file = Path("logLastPipeline.txt")
if log_file.exists():
    print(f"\n[OK] Fichier de log créé: {log_file.absolute()}")
    print(f"[OK] Taille: {log_file.stat().st_size} bytes")

    # Afficher les dernières lignes
    content = log_file.read_text(encoding="utf-8")
    lines = content.strip().split("\n")
    print(f"[OK] Nombre de lignes: {len(lines)}")

    print("\n--- Aperçu du fichier (5 dernières lignes) ---")
    for line in lines[-5:]:
        print(line)
else:
    print("[ERREUR] Fichier de log non créé!")
