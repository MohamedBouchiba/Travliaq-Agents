# Exemples pour la pipeline CrewAI

Ce dossier contient des charges utiles prêtes à l'emploi pour exécuter la pipeline
Travliaq en dehors de l'API.

- `traveller_persona_input.json.example` : exemple complet reçu après l'étape
  d'inférence persona. Copiez ce fichier en `traveller_persona_input.json` et
  adaptez-le si nécessaire pour vos tests locaux. Les fichiers `.json` sont ignorés
  par git pour éviter de versionner des données sensibles.

## Lancer la pipeline en ligne de commande

```bash
python -m app.crew_pipeline --input-file examples/traveller_persona_input.json
```

Pour reconstruire les données à partir d'un identifiant Supabase :

```bash
python -m app.crew_pipeline --questionnaire-id <UUID>
```

Ajoutez `--include-raw` pour afficher la réponse brute renvoyée par CrewAI.

## Sorties persistées

Chaque exécution crée un dossier dédié dans `output/crew_runs/<run_id>/` qui
contient :

- `run_output.json` : le payload complet enrichi (input + analyse).
- `tasks/*.json` : les réponses individuelles de chaque tâche CrewAI.

Ces fichiers permettent d'auditer facilement le raisonnement de chaque agent.
