# Travliaq Agents 🌍✈️

> **Orchestration d'agents IA pour la génération de voyages ultra-personnalisés.**

Ce projet contient la logique "Cerveau" de Travliaq. Il utilise **CrewAI** pour orchestrer des agents autonomes capables d'analyser des profils voyageurs, de vérifier la faisabilité des demandes et de générer des spécifications techniques précises.

---

## 🏗️ Architecture Globale

Le pipeline est divisé en deux phases distinctes, combinant des scripts Python déterministes (🐍) et des agents IA génératifs (🤖).

### Phase 1 : Enrichissement et Catégorisation Utilisateur

Cette phase transforme les données brutes du questionnaire en un profil voyageur structuré et validé.

1.  **🐍 Questionnaire Submission (Script)**

    - **Type** : Point d'entrée Python.
    - **Action** : Réception du payload JSON depuis l'API/Supabase.
    - **Rôle** : Validation technique initiale des données entrantes.

2.  **🐍 Persona Inference (Script)**

    - **Type** : Service Python Déterministe (`PersonaInferenceService`).
    - **Action** : Calcul algorithmique du "score" persona basé sur les réponses (ex: 60% Nature, 40% Luxe).
    - **Output** : Contexte structuré injecté dans le prompt des agents.

3.  **🤖 Narratif User (Agent : Traveller Insights Analyst)**

    - **Type** : Agent IA (CrewAI).
    - **Action** : Analyse psychologique et rédactionnelle.
    - **Outil MCP** : `read_les_macro_personas...` (Consultation obligatoire).
    - **Output** : "Traveller Profile Brief" (Narratif immersif + Analyse des besoins).

4.  **🤖 Challenger Narratif (Agent : Persona Quality Challenger)**

    - **Type** : Agent IA (CrewAI).
    - **Action** : Fact-checking et critique constructive.
    - **Outil MCP** : `read_guide_tourisme...` (Vérification faisabilité budget/saison).
    - **Output** : "Persona Challenge Review" (Validation des hypothèses).

5.  **🤖 Output Structuré (Agent : Trip Specifications Architect)**
    - **Type** : Agent IA (CrewAI).
    - **Action** : Normalisation technique.
    - **Output** : `normalized_trip_request.yaml` (Fichier pivot pour la Phase 2).

---

### Phase 2 : Sélection de la Destination (Target Architecture)

Cette phase utilise le profil validé pour sélectionner et affiner la destination idéale.

6.  **🤖 Proposé 4 Destinations (Agent : Destination Scout)**

    - **Type** : Agent IA.
    - **Input** : `normalized_trip_request.yaml`.
    - **Action** : Recherche large et proposition de 4 options viables.

7.  **🤖 Enrichissement Data (Agents Spécialisés)**

    - **Résumé Destination** : Génération de descriptions attractives.
    - **Prix Moyen Vols** : Consultation API (Skyscanner/Amadeus via MCP).
    - **Prix Moyen Hôtel** : Consultation API (Booking/Expedia via MCP).

8.  **🤖 Choix de la Destination (Agent : Decision Maker)**

    - **Type** : Agent IA.
    - **Action** : Sélection de la meilleure option basée sur le rapport Qualité/Prix/Expérience.

9.  **🤖 Challenger Destination (Agent : Feasibility Expert)**
    - **Type** : Agent IA.
    - **Action** : Validation finale (Sécurité, Visas, Santé).
    - **Output Final** : Itinéraire macro validé.

---

## 🚀 Installation & Démarrage

### Pré-requis

- Python 3.10+
- Un serveur MCP Travliaq accessible (local ou distant).
- Clés API (OpenAI, Groq, ou Azure).

### Configuration

1.  Copiez `.env.example` vers `.env` :
    ```bash
    cp .env.example .env
    ```
2.  Remplissez les variables :
    - `OPENAI_API_KEY` (ou autre provider)
    - `MCP_SERVER_URL` (ex: `http://localhost:8000/sse` ou URL Railway)
    - `ENVIRONMENT=development` (pour sauvegarder les outputs sur disque)

### Installation

```bash
pip install -r requirements.txt
```

---

## 💻 Utilisation

### Via CLI (Recommandé)

Pour lancer une analyse sur un questionnaire spécifique :

```bash
python crew_pipeline_cli.py --questionnaire-id <UUID>
```

### Outputs (Phase 1)

En mode `development`, les résultats sont sauvegardés dans `output/<run_id>/` :

- `run_output.yaml` : Résultat complet de l'exécution.
- `tasks/` :
  - `traveller_profile_brief.yaml`
  - `persona_challenge_review.yaml`
  - `trip_specifications_design.yaml` (Contient le `normalized_trip_request`)

---

## 🛠️ Stack Technique

- **Framework Agents** : [CrewAI](https://crewai.com)
- **Connectivité** : [Model Context Protocol (MCP)](https://modelcontextprotocol.io)
- **Langage** : Python 3.11
- **Format de Données** : YAML Strict (Inputs & Outputs)

---

## 🤝 Contribution

1.  Les agents sont configurés dans `app/crew_pipeline/config/agents.yaml`.
2.  Les tâches sont définies dans `app/crew_pipeline/config/tasks.yaml`.
3.  Toute modification du flux doit respecter l'obligation de **YAML Only** et l'utilisation des outils MCP.
