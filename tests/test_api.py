#!/usr/bin/env python3
"""Script de test rapide pour l'API."""

import requests
import json

BASE_URL = "http://localhost:8000"
TEST_QUESTIONNAIRE_ID = "c92a18b0-c2d4-4903-abdb-6e7669eb0633"


def test_health():
    """Test du health check."""
    print("🏥 Test du health check...")
    response = requests.get(f"{BASE_URL}/api/v1/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    print()


def test_process_post():
    """Test du traitement complet via POST."""
    print(f"🚀 Test POST /api/v1/process avec ID: {TEST_QUESTIONNAIRE_ID}")
    print("=" * 80)

    response = requests.post(
        f"{BASE_URL}/api/v1/process",
        json={"questionnaire_id": TEST_QUESTIONNAIRE_ID}
    )
    print(f"Status: {response.status_code}")

    if response.status_code == 200:
        data = response.json()

        print(f"\n✅ Traitement réussi!")
        print(f"Questionnaire ID: {data['questionnaire_id']}")

        print(f"\n📊 DONNÉES QUESTIONNAIRE:")
        q_data = data['questionnaire_data']
        print(f"  • Email: {q_data.get('email')}")
        print(f"  • Groupe: {q_data.get('groupe_voyage')}")
        print(f"  • Destination: {q_data.get('destination')}")
        print(f"  • Budget: {q_data.get('budget_par_personne')}")
        print(f"  • Durée: {q_data.get('duree')}")

        print(f"\n🧠 INFÉRENCE PERSONA:")
        persona = data['persona_inference']['persona']
        print(f"  • Persona principal: {persona['principal']}")
        print(f"  • Confiance: {persona['confiance']}%")
        print(f"  • Niveau: {persona['niveau']}")
        print(f"  • Action: {persona['action_recommandee']}")

        if persona['profils_emergents']:
            print(f"\n🌟 Profils émergents:")
            for profil in persona['profils_emergents']:
                print(f"  • {profil['nom']}: {profil['confiance']}%")

        caracteristiques = data['persona_inference']['caracteristiques_sures']
        if caracteristiques:
            print(f"\n✅ Caractéristiques sûres:")
            for carac in caracteristiques:
                print(f"  • {carac}")

        incertitudes = data['persona_inference']['incertitudes']
        if incertitudes:
            print(f"\n❓ Incertitudes:")
            for incert in incertitudes:
                print(f"  • {incert}")

        signaux = data['persona_inference']['signaux']
        print(f"\n📊 Signaux détectés:")
        print(f"  • Signaux forts: {len(signaux['forts'])}")
        print(f"  • Signaux moyens: {len(signaux['moyens'])}")

        recommandations = data['persona_inference']['recommandations']
        if recommandations:
            print(f"\n💡 Recommandations:")
            for reco in recommandations:
                print(f"  {reco}")

        print(f"\n📄 JSON COMPLET (persona_inference):")
        print(json.dumps(data['persona_inference'], indent=2, ensure_ascii=False))

    else:
        print(f"❌ Erreur: {response.text}")
    print()


def test_process_get():
    """Test du traitement complet via GET."""
    print(f"🚀 Test GET /api/v1/process/{TEST_QUESTIONNAIRE_ID}")
    print("=" * 80)

    response = requests.get(f"{BASE_URL}/api/v1/process/{TEST_QUESTIONNAIRE_ID}")
    print(f"Status: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        persona = data['persona_inference']['persona']
        print(f"✅ Persona: {persona['principal']}")
        print(f"📊 Confiance: {persona['confiance']}% ({persona['niveau']})")
    else:
        print(f"❌ Erreur: {response.text}")
    print()


if __name__ == "__main__":
    print("🚀 Test de l'API Travliaq-Agents\n")
    print("=" * 80)

    try:
        test_health()
        print("=" * 80)
        print("\n🧠 TEST COMPLET (Questionnaire + Inférence)\n")
        print("=" * 80)
        test_process_post()
        test_process_get()
        print("=" * 80)
        print("\n✅ Tous les tests terminés!")
    except requests.exceptions.ConnectionError:
        print("❌ Erreur: L'API n'est pas accessible.")
        print("   Démarrez l'API avec: python run.py")
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback

        traceback.print_exc()