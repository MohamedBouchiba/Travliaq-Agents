"""Test du système de logging centralisé."""
import logging
from pathlib import Path
import pytest

from app.crew_pipeline.logging_config import setup_pipeline_logging


def test_logging_creates_file_and_overwrites():
    """Vérifie que le fichier de log est créé et écrasé à chaque fois."""
    # Créer un fichier temporaire pour les tests
    test_log_file = Path("test_log_temp.txt")

    # Supprimer le fichier s'il existe déjà
    if test_log_file.exists():
        test_log_file.unlink()

    # Premier run : initialiser le logging
    setup_pipeline_logging(
        log_file=test_log_file,
        level=logging.INFO,
        console_output=False,  # Désactiver console pour le test
    )

    # Écrire quelques logs
    logger = logging.getLogger("test")
    logger.info("Premier message")
    logger.warning("Deuxième message")

    # Vérifier que le fichier existe
    assert test_log_file.exists()

    # Lire le contenu
    content1 = test_log_file.read_text(encoding="utf-8")
    assert "Premier message" in content1
    assert "Deuxième message" in content1
    assert "LOGS INITIALIZED" in content1

    # Compter les lignes
    lines1 = content1.strip().split("\n")
    num_lines1 = len(lines1)

    print(f"[OK] Premier run: {num_lines1} lignes écrites")

    # Second run : réinitialiser le logging (doit ÉCRASER le fichier)
    setup_pipeline_logging(
        log_file=test_log_file,
        level=logging.INFO,
        console_output=False,
    )

    # Écrire de nouveaux logs (différents)
    logger2 = logging.getLogger("test2")
    logger2.info("Troisième message (nouveau run)")
    logger2.error("Quatrième message (nouveau run)")

    # Lire le nouveau contenu
    content2 = test_log_file.read_text(encoding="utf-8")

    # Vérifier que les ANCIENS messages n'existent PLUS
    assert "Premier message" not in content2
    assert "Deuxième message" not in content2

    # Vérifier que les NOUVEAUX messages existent
    assert "Troisième message (nouveau run)" in content2
    assert "Quatrième message (nouveau run)" in content2
    assert "LOGS INITIALIZED" in content2

    lines2 = content2.strip().split("\n")
    num_lines2 = len(lines2)

    print(f"[OK] Second run: {num_lines2} lignes écrites (fichier écrasé)")
    print(f"[OK] Ancien contenu effacé, nouveau contenu présent")

    # Nettoyer : fermer les handlers avant de supprimer le fichier (Windows)
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)

    test_log_file.unlink()


def test_logging_captures_all_modules():
    """Vérifie que les logs de TOUS les modules sont capturés."""
    test_log_file = Path("test_log_capture.txt")

    if test_log_file.exists():
        test_log_file.unlink()

    setup_pipeline_logging(
        log_file=test_log_file,
        level=logging.INFO,
        console_output=False,
    )

    # Logger depuis différents modules simulés
    logger_pipeline = logging.getLogger("app.crew_pipeline.pipeline")
    logger_mcp = logging.getLogger("app.crew_pipeline.mcp_tools")
    logger_script = logging.getLogger("app.crew_pipeline.scripts")
    logger_root = logging.getLogger()

    logger_pipeline.info("Message depuis pipeline")
    logger_mcp.warning("Message depuis mcp_tools")
    logger_script.error("Message depuis scripts")
    logger_root.info("Message depuis root logger")

    content = test_log_file.read_text(encoding="utf-8")

    assert "Message depuis pipeline" in content
    assert "Message depuis mcp_tools" in content
    assert "Message depuis scripts" in content
    assert "Message depuis root logger" in content

    print("[OK] Tous les modules loggent dans le même fichier")

    # Nettoyer : fermer les handlers avant de supprimer le fichier (Windows)
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)

    test_log_file.unlink()


def test_default_log_file_location():
    """Vérifie que le fichier par défaut est créé à la racine du projet."""
    # Ne pas spécifier de log_file = utilise le défaut (logLastPipeline.txt)
    setup_pipeline_logging(level=logging.INFO, console_output=False)

    logger = logging.getLogger("test_default")
    logger.info("Test message pour fichier par défaut")

    # Vérifier que le fichier existe à la racine
    project_root = Path(__file__).resolve().parent.parent
    default_log_file = project_root / "logLastPipeline.txt"

    assert default_log_file.exists(), f"Fichier attendu: {default_log_file}"

    content = default_log_file.read_text(encoding="utf-8")
    assert "Test message pour fichier par défaut" in content

    print(f"[OK] Fichier par défaut créé: {default_log_file}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
