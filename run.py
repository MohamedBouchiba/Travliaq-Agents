"""Script de lancement de l'API Travliaq-Agents (multi-plateforme)."""

import sys
import os
import platform

# Ajouter le répertoire racine au PYTHONPATH
root_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, root_dir)


def get_display_host(host: str) -> str:
    """Convertit 0.0.0.0 en localhost pour l'affichage."""
    return "localhost" if host == "0.0.0.0" else host


def print_startup_info(host: str, port: int):
    """Affiche les informations de démarrage selon l'OS."""
    display_host = get_display_host(host)
    os_name = platform.system()

    print("=" * 60)
    print("🚀 Travliaq-Agents API")
    print("=" * 60)
    print(f"📍 URL locale:        http://{display_host}:{port}")
    print(f"📚 Documentation:     http://{display_host}:{port}/docs")
    print(f"📖 ReDoc:             http://{display_host}:{port}/redoc")
    print(f"💻 Système:           {os_name} ({platform.machine()})")
    print(f"🐍 Python:            {platform.python_version()}")
    print("=" * 60)
    print()

    if os_name == "Windows":
        print("💡 Arrêter: Ctrl+C ou Ctrl+Break")
    else:
        print("💡 Arrêter: Ctrl+C")
    print()


if __name__ == "__main__":
    try:
        import uvicorn
        from app.config import settings

        print_startup_info(settings.api_host, settings.api_port)

        # Configuration adaptée selon l'OS
        reload_enabled = settings.api_reload

        # Sur Windows, on peut avoir des problèmes avec reload en mode multiprocess
        if platform.system() == "Windows" and reload_enabled:
            print("⚠️  Mode reload activé (peut être instable sur Windows)")
            print()

        uvicorn.run(
            "app.api.main:app",
            host=settings.api_host,
            port=settings.api_port,
            reload=reload_enabled,
            log_level=settings.log_level.lower(),
            access_log=True
        )

    except KeyboardInterrupt:
        print("\n\n👋 Arrêt de l'API...")
        sys.exit(0)
    except ImportError as e:
        print(f"\n❌ Erreur: Module manquant - {e}")
        print("\n💡 Solution:")
        print("   pip install -r requirements.txt")
        print("   ou")
        print("   .venv/Scripts/pip install -r requirements.txt  (Windows)")
        print("   .venv/bin/pip install -r requirements.txt      (Linux/Mac)")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Erreur inattendue: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)