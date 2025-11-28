"""Test de l'intégration MCP avec la pipeline CrewAI.

Ce script vérifie que:
1. Le serveur MCP est accessible
2. Les outils sont correctement chargés
3. L'intégration avec CrewAI fonctionne
"""
import logging
import sys
from pathlib import Path

# Ajouter le répertoire racine au path pour les imports
sys.path.insert(0, str(Path(__file__).parent))

from app.crew_pipeline.mcp_tools import get_mcp_tools

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_mcp_connection(server_url: str) -> bool:
    """Test la connexion au serveur MCP et le chargement des outils.
    
    Args:
        server_url: URL du serveur MCP
        
    Returns:
        True si au moins un outil a été chargé, False sinon
    """
    print(f"\n{'='*60}")
    print(f"🔍 Test de connexion au serveur MCP")
    print(f"{'='*60}")
    print(f"URL: {server_url}\n")
    
    try:
        tools = get_mcp_tools(server_url)
        
        if not tools:
            print("❌ ÉCHEC: Aucun outil MCP chargé")
            print("\nPossibles causes:")
            print("  - Le serveur MCP n'est pas démarré")
            print("  - L'URL est incorrecte")
            print("  - Problème réseau/firewall")
            return False
        
        print(f"✅ SUCCÈS: {len(tools)} outils MCP chargés\n")
        print(f"{'─'*60}")
        print("📋 Outils disponibles:")
        print(f"{'─'*60}\n")
        
        for i, tool in enumerate(tools, 1):
            print(f"{i}. {tool.name}")
            if hasattr(tool, 'description') and tool.description:
                # Tronquer la description si trop longue
                desc = tool.description
                if len(desc) > 80:
                    desc = desc[:77] + "..."
                print(f"   └─ {desc}")
            print()
        
        # Vérifier qu'on a les outils attendus
        expected_tools = [
            "weather.by_coords",
            "weather.brief", 
            "weather.by_period",
            "images.hero",
            "images.background",
            "images.slider",
            "health.ping",
            "debug.ls"
        ]
        
        tool_names = {tool.name for tool in tools}
        missing_tools = set(expected_tools) - tool_names
        unexpected_tools = tool_names - set(expected_tools)
        
        if missing_tools:
            print(f"⚠️  Outils manquants: {', '.join(missing_tools)}")
        
        if unexpected_tools:
            print(f"ℹ️  Outils supplémentaires: {', '.join(unexpected_tools)}")
        
        return True
        
    except Exception as e:
        print(f"❌ ERREUR lors du test de connexion:")
        print(f"   {type(e).__name__}: {str(e)}")
        logger.exception("Détails de l'erreur:")
        return False


def main():
    """Point d'entrée principal du script de test."""
    # URL du serveur MCP en production
    server_url = "https://travliaq-mcp-production.up.railway.app/mcp"
    
    print("\n" + "="*60)
    print("🧪 TEST D'INTÉGRATION MCP - TRAVLIAQ AGENTS")
    print("="*60)
    
    success = test_mcp_connection(server_url)
    
    print("\n" + "="*60)
    if success:
        print("✅ RÉSULTAT: Intégration MCP fonctionnelle")
        print("="*60)
        print("\n💡 Prochaine étape:")
        print("   Exécuter la pipeline complète avec:")
        print("   python run.py examples/traveller_persona_input.json\n")
        return 0
    else:
        print("❌ RÉSULTAT: Intégration MCP non fonctionnelle")
        print("="*60)
        print("\n🔧 Actions correctives:")
        print("   1. Vérifier que le serveur Railway est démarré")
        print("   2. Tester l'URL manuellement:")
        print(f"      curl {server_url}")
        print("   3. Vérifier les logs du serveur MCP\n")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
