"""Script de test rapide pour exécuter la pipeline avec un ID questionnaire pré-configuré.

Usage:
    python examples/test_pipeline.py
"""

import json
import sys
from pathlib import Path

# Ajouter le répertoire parent au path pour importer app
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.crew_pipeline.pipeline import run_pipeline_from_payload


# ====================================================================
# CONFIGURATION - Modifier l'ID du questionnaire ici
# ====================================================================
QUESTIONNAIRE_ID = "c786404a-18ae-4a1f-b8a1-403a3de78540"
# ====================================================================


def main():
    """Exécute la pipeline avec un exemple local."""
    
    print("🚀 Test de la pipeline CrewAI")
    print(f"📋 Questionnaire ID: {QUESTIONNAIRE_ID}")
    print("-" * 60)
    
    # Charger l'exemple depuis le fichier JSON
    example_file = Path(__file__).parent / "traveller_persona_input.json"
    
    if not example_file.exists():
        print(f"❌ Fichier d'exemple non trouvé: {example_file}")
        print("💡 Utilisez plutôt: python crew_pipeline_cli.py --input-file examples/traveller_persona_input.json")
        return 1
    
    with open(example_file, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    
    # Optionnel: Remplacer l'ID dans le payload si configuré
    if QUESTIONNAIRE_ID:
        if 'questionnaire_data' in payload and isinstance(payload['questionnaire_data'], dict):
            payload['questionnaire_data']['id'] = QUESTIONNAIRE_ID
            payload['questionnaire_id'] = QUESTIONNAIRE_ID
    
    print(f"✅ Payload chargé depuis: {example_file.name}")
    print(f"📊 Questionnaire: {payload.get('questionnaire_data', {}).get('destination', 'N/A')}")
    print(f"👤 Persona: {payload.get('persona_inference', {}).get('id', 'N/A')}")
    print("-" * 60)
    
    try:
        # Exécuter la pipeline
        print("\n🔄 Exécution de la pipeline...\n")
        result = run_pipeline_from_payload(payload)
        
        # Afficher les résultats
        print("\n" + "=" * 60)
        print("✅ PIPELINE TERMINÉE AVEC SUCCÈS")
        print("=" * 60)
        
        run_id = result.get('run_id', 'unknown')
        print(f"\n📁 Run ID: {run_id}")
        print(f"📊 Status: {result.get('status', 'N/A')}")
        
        # Métriques si disponibles
        if 'quality_scores' in result:
            scores = result['quality_scores']
            print(f"\n📈 Scores de Qualité:")
            print(f"   - Global: {scores.get('overall', 0):.2%}")
            print(f"   - Complétude: {scores.get('completeness', 0):.2%}")
            print(f"   - Narratif: {scores.get('narrative_quality', 0):.2%}")
        
        # Info persona
        if 'persona_analysis' in result:
            persona = result['persona_analysis']
            print(f"\n👤 Analyse Persona:")
            print(f"   - Résumé: {persona.get('persona_summary', 'N/A')[:80]}...")
            print(f"   - Points forts: {len(persona.get('pros', []))}")
            print(f"   - Points d'attention: {len(persona.get('cons', []))}")
            print(f"   - Besoins critiques: {len(persona.get('critical_needs', []))}")
        
        # Fichiers générés
        print(f"\n📂 Fichiers générés dans: output/{run_id}/")
        print("   - run_output.json")
        print("   - metrics.json")
        print("   - tasks/*.json")
        
        print("\n💡 Pour voir les détails complets:")
        print(f"   cat output/{run_id}/run_output.json")
        print(f"   cat output/{run_id}/metrics.json")
        
        return 0
        
    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ ERREUR LORS DE L'EXÉCUTION")
        print("=" * 60)
        print(f"\n{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
