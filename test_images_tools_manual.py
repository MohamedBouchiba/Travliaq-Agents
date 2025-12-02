"""Test manuel des tools images.hero et images.background."""
import asyncio
import json
from app.crew_pipeline.mcp_tools import get_mcp_tools
from app.config import settings


async def test_images_tools():
    """Test manuel des outils de génération d'images."""
    print("=" * 80)
    print("TEST MANUEL DES TOOLS D'IMAGES")
    print("=" * 80)

    # Charger les outils MCP
    print(f"\n[1/4] Connexion au serveur MCP: {settings.mcp_server_url}")
    try:
        tools = get_mcp_tools(settings.mcp_server_url)
        print(f"[OK] {len(tools)} outils chargés")
    except Exception as e:
        print(f"[ERREUR] Échec de connexion: {e}")
        return

    # Trouver les tools images
    hero_tool = None
    background_tool = None

    for tool in tools:
        if hasattr(tool, 'name'):
            if tool.name == "images.hero":
                hero_tool = tool
                print(f"[OK] Tool images.hero trouvé")
            elif tool.name == "images.background":
                background_tool = tool
                print(f"[OK] Tool images.background trouvé")

    if not hero_tool or not background_tool:
        print("[ERREUR] Tools images non trouvés")
        return

    # Test 1 : images.hero
    print("\n[2/4] Test images.hero")
    print("Arguments :")
    hero_args = {
        "city": "Paris",
        "country": "France",
        "trip_name": "Paris Test",
        "trip_folder": "Paris_Test_2025"
    }
    print(json.dumps(hero_args, indent=2))

    try:
        print("\nAppel du tool...")
        hero_result = hero_tool._run(**hero_args)
        print("[OK] Réponse reçue:")
        print(json.dumps(hero_result, indent=2))

        # Vérifier le format
        if isinstance(hero_result, dict):
            if "url" in hero_result:
                print(f"\n[OK] URL extraite: {hero_result['url']}")
            else:
                print("[ERREUR] Champ 'url' manquant dans la réponse")
        else:
            print(f"[ERREUR] Type de réponse incorrect: {type(hero_result)}")
            print(f"Contenu: {hero_result}")

    except Exception as e:
        print(f"[ERREUR] images.hero échoué: {e}")
        import traceback
        traceback.print_exc()
        return

    # Test 2 : images.background
    print("\n[3/4] Test images.background")
    print("Arguments :")
    background_args = {
        "activity": "visiting Eiffel Tower",
        "city": "Paris",
        "country": "France",
        "trip_name": "Paris Test",
        "trip_folder": "Paris_Test_2025"
    }
    print(json.dumps(background_args, indent=2))

    try:
        print("\nAppel du tool...")
        background_result = background_tool._run(**background_args)
        print("[OK] Réponse reçue:")
        print(json.dumps(background_result, indent=2))

        # Vérifier le format
        if isinstance(background_result, dict):
            if "url" in background_result:
                print(f"\n[OK] URL extraite: {background_result['url']}")
            else:
                print("[ERREUR] Champ 'url' manquant dans la réponse")
        else:
            print(f"[ERREUR] Type de réponse incorrect: {type(background_result)}")
            print(f"Contenu: {background_result}")

    except Exception as e:
        print(f"[ERREUR] images.background échoué: {e}")
        import traceback
        traceback.print_exc()
        return

    # Test 3 : Vérifier que les URLs sont différentes
    print("\n[4/4] Vérification de cohérence")
    try:
        hero_url = hero_result.get("url") if isinstance(hero_result, dict) else None
        background_url = background_result.get("url") if isinstance(background_result, dict) else None

        if hero_url and background_url:
            if hero_url != background_url:
                print("[OK] Les URLs sont différentes (attendu)")
                print(f"  Hero     : {hero_url[:60]}...")
                print(f"  Background: {background_url[:60]}...")
            else:
                print("[AVERTISSEMENT] Les URLs sont identiques (inattendu)")

            # Vérifier qu'elles contiennent bien le trip_folder
            if "Paris_Test_2025" in hero_url:
                print("[OK] trip_folder présent dans l'URL hero")
            else:
                print("[AVERTISSEMENT] trip_folder absent de l'URL hero")

            if "Paris_Test_2025" in background_url:
                print("[OK] trip_folder présent dans l'URL background")
            else:
                print("[AVERTISSEMENT] trip_folder absent de l'URL background")

        else:
            print("[ERREUR] Impossible d'extraire les URLs")

    except Exception as e:
        print(f"[ERREUR] Vérification échouée: {e}")

    print("\n" + "=" * 80)
    print("TEST TERMINÉ")
    print("=" * 80)


if __name__ == "__main__":
    # Exécuter le test
    print("\nDémarrage du test...")
    print("(Cela peut prendre 30-60 secondes pour générer les images)\n")

    try:
        asyncio.run(test_images_tools())
    except KeyboardInterrupt:
        print("\n\n[INFO] Test interrompu par l'utilisateur")
    except Exception as e:
        print(f"\n\n[ERREUR FATALE] {e}")
        import traceback
        traceback.print_exc()
