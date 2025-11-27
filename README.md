# Travliaq-Agents

**Pipeline CrewAI intelligente pour analyser les questionnaires voyage et générer des spécifications de trip structurées.**

Utilise des agents IA multi-rôles (analyste, challenger, architecte) avec outputs validés par Pydantic, observabilité complète et intégration MCP.

---

## 🚀 Démarrage Rapide

### 1. Installation

```bash
# Cloner le projet
git clone git@github.com:MohamedBouchiba/Travliaq-Agents.git
cd Travliaq-Agents

# Créer et activer l'environnement virtuel
python -m venv .venv
source .venv/Scripts/activate  # Windows Git Bash
# ou: .venv\Scripts\activate   # Windows CMD
# ou: source .venv/bin/activate # Linux/macOS

# Installer les dépendances
pip install -r requirements.txt

# Configurer les variables d'environnement
# Éditer .env et ajouter votre OPENAI_API_KEY
```

---

## 📋 Méthodes d'Exécution

### Option 1: API FastAPI (Production)

Démarrer le serveur API :

```bash
# Méthode 1 - Script Python
python run.py

# Méthode 2 - Uvicorn direct
uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
```

L'API sera accessible sur **http://localhost:8000**

- Documentation: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

**Appeler la pipeline via l'API** :

```bash
# Health check
curl http://localhost:8000/api/v1/health

# Exécuter la pipeline avec un questionnaire-id
curl -X POST "http://localhost:8000/api/v1/questionnaire" \
  -H "Content-Type: application/json" \
  -d '{"questionnaire_id": "c786404a-18ae-4a1f-b8a1-403a3de78540"}'
```

---

### Option 2: CLI avec ID Questionnaire

Exécuter la pipeline directement depuis la ligne de commande :

```bash
# Avec un ID questionnaire depuis Supabase
python crew_pipeline_cli.py --questionnaire-id c786404a-18ae-4a1f-b8a1-403a3de78540

# Avec un fichier JSON local
python crew_pipeline_cli.py --input-file examples/traveller_persona_input.json

# Forcer un modèle spécifique
python crew_pipeline_cli.py \
  --questionnaire-id c786404a-18ae-4a1f-b8a1-403a3de78540 \
  --llm-provider openai \
  --model gpt-4o-mini
```

---

### Option 3: Script avec ID Pré-configuré

**Méthode la plus simple pour tester** :

1. Éditer le fichier de test pour définir l'ID :

```python
# Dans examples/test_pipeline.py ou créer un nouveau script
from app.crew_pipeline.pipeline import run_pipeline_from_payload
import json

# Charger un exemple ou définir un payload
with open('examples/traveller_persona_input.json') as f:
    payload = json.load(f)

# Exécuter la pipeline
result = run_pipeline_from_payload(payload)
print(json.dumps(result, indent=2))
```

2. Exécuter le script :

```bash
python examples/test_pipeline.py
```

---

## 📊 Outputs Générés

Chaque exécution crée un dossier `output/<run_id>/` contenant :

```
output/
└── <run_id>/
    ├── run_output.json          # Résultat final enrichi
    ├── metrics.json              # Métriques de performance (durée, tokens, coûts)
    └── tasks/                    # Outputs par tâche
        ├── traveller_profile_brief.json
        ├── persona_challenge_review.json
        └── trip_specifications_design.json
```

**Métriques collectées** :

- ⏱️ Durée d'exécution (totale et par agent)
- 🔢 Nombre de tokens utilisés
- 💰 Coût estimé (USD)
- 📊 Scores de qualité des outputs

---

## 🏗️ Architecture

```
Questionnaire + Persona Inference
           ↓
    Agent 1: Analyste (PersonaAnalysisOutput)
           ↓
    Agent 2: Challenger (PersonaChallengeOutput)
           ↓
    Agent 3: Architecte (TripSpecificationsOutput)
           ↓
    Trip Request Normalisé + Métriques
```

**Best Practices Appliquées** :

- ✅ Outputs structurés avec Pydantic
- ✅ Observabilité et métriques complètes
- ✅ Retry logic et timeouts pour outils MCP
- ✅ Optimisation LLM (max_iter, memory)
- ✅ Tests unitaires automatisés

---

## 📚 Documentation Détaillée

- **[Pipeline Workflow](documentation/trip_generation_workflow.md)** - Flux détaillé de la pipeline
- **[Configuration](app/crew_pipeline/config/)** - Agents, tâches et crew
- **[Best Practices](C:/Users/User/.gemini/antigravity/brain/07d5ff8c-fec0-4cb9-9ee0-0746393a7ee4/implementation_plan.md)** - Plan d'implémentation
- **[Walkthrough](C:/Users/User/.gemini/antigravity/brain/07d5ff8c-fec0-4cb9-9ee0-0746393a7ee4/walkthrough.md)** - Modifications apportées

---

## 🧪 Tests

```bash
# Tests unitaires des modèles
pytest tests/test_models.py -v

# Tests complets
pytest tests/ -v

# Coverage
pytest tests/ --cov=app --cov-report=html
```

---

## 🔧 Configuration

### Variables d'Environnement (.env)

```env
# LLM Provider
LLM_PROVIDER=openai
OPENAI_API_KEY=your_key_here
MODEL=gpt-4o-mini

# Supabase
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
POSTGRES_HOST=your_postgres_host
POSTGRES_DB=postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password

# MCP Server
MCP_SERVER_URL=https://travliaq-mcp-production.up.railway.app/mcp

# CrewAI
CREW_OUTPUT_DIR=output
VERBOSE=true
```

---

## 🐛 Troubleshooting

### ModuleNotFoundError: No module named 'X'

```bash
# Réinstaller les dépendances dans le venv
source .venv/Scripts/activate  # Activer le venv
pip install -r requirements.txt
```

### Erreur psycopg2

```bash
# Si .venv corrompu, le recréer
rm -rf .venv
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

### Port 8000 déjà utilisé

Modifier dans `.env` :

```env
API_PORT=8001
```

---

## 📦 Structure du Projet

```
Travliaq-Agents/
├── app/
│   ├── api/                      # API FastAPI
│   ├── crew_pipeline/            # Pipeline CrewAI
│   │   ├── config/               # Agents, tâches, crew (YAML)
│   │   ├── models.py             # Modèles Pydantic
│   │   ├── observability.py      # Métriques & monitoring
│   │   ├── pipeline.py           # Orchestration principale
│   │   └── mcp_tools.py          # Outils MCP
│   └── services/                 # Services (Supabase)
├── tests/                        # Tests unitaires
├── examples/                     # Exemples et fixtures
├── output/                       # Outputs générés
├── documentation/                # Documentation
├── crew_pipeline_cli.py          # CLI principal
└── run.py                        # Launcher API
```

---

## 🤝 Contact & Support

- **Repository**: [Travliaq-Agents](https://github.com/MohamedBouchiba/Travliaq-Agents)
- **Documentation**: Voir `documentation/`
- **Issues**: GitHub Issues

## Architecture

```
API Endpoint → PostgreSQL (Supabase) → Récupération Questionnaire → CrewAI Pipeline → JSON Trip
```

## Installation

### 1. Cloner le projet

```bash
git clone git@github.com:MohamedBouchiba/Travliaq-Agents.git
cd Travliaq-Agents
```

### 2. Créer un environnement virtuel

**Windows:**

```bash
python -m venv .venv
.venv\Scripts\activate
```

**Linux/macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Installer les dépendances

**Méthode automatique:**

Windows:

```bash
install.bat
```

Linux/macOS:

```bash
chmod +x install.sh
./install.sh

# Ou avec make
make install
```

**Méthode manuelle:**

```bash
pip install -r requirements.txt
```

### 4. Vérifier la configuration

Le fichier `.env` est déjà configuré avec les credentials Supabase.

> ℹ️ Remplacez la valeur `OPENAI_API_KEY` ou laissez-la vide si vous
> préférez fournir la clé via une variable d'environnement (par exemple
> `set OPENAI_API_KEY=...` sous Windows ou `export OPENAI_API_KEY=...` sur
> macOS/Linux). Les valeurs factices comme `your_key_here` sont ignorées
> automatiquement afin de privilégier les clés réellement définies.

```bash
cat .env  # Linux/macOS
type .env # Windows
```

## Démarrage

### Lancer l'API

**Méthode 1 - Script automatique (recommandé):**

Windows:

```bash
start.bat
# Ou double-clic sur start.bat
```

Linux/macOS:

```bash
./start.sh

# Ou avec make
make run
```

**Méthode 2 - Script Python (toutes plateformes):**

```bash
python run.py      # Windows
python3 run.py     # Linux/macOS
```

**Méthode 3 - Uvicorn directement:**

```bash
uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
```

L'API sera accessible sur **http://localhost:8000**

### Affichage au démarrage

```
============================================================
🚀 Travliaq-Agents API
============================================================
📍 URL locale:        http://localhost:8000
📚 Documentation:     http://localhost:8000/docs
📖 ReDoc:             http://localhost:8000/redoc
💻 Système:           Windows (AMD64)
🐍 Python:            3.11.0
============================================================

💡 Arrêter: Ctrl+C
```

### Documentation interactive

Une fois l'API lancée, accédez à:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Utilisation

### 1. Health Check

Vérifier que l'API et la base de données sont accessibles:

```bash
curl http://localhost:8000/api/v1/health
```

**Réponse:**

```json
{
  "status": "ok",
  "message": "Service is healthy"
}
```

### 2. Récupérer un questionnaire (POST)

```bash
curl -X POST "http://localhost:8000/api/v1/questionnaire" \
  -H "Content-Type: application/json" \
  -d '{"questionnaire_id": "c92a18b0-c2d4-4903-abdb-6e7669eb0633"}'
```

### 3. Récupérer un questionnaire (GET)

```bash
curl http://localhost:8000/api/v1/questionnaire/c92a18b0-c2d4-4903-abdb-6e7669eb0633
```

**Réponse:**

```json
{
  "status": "ok",
  "questionnaire_id": "c92a18b0-c2d4-4903-abdb-6e7669eb0633",
  "data": {
    "id": "c92a18b0-c2d4-4903-abdb-6e7669eb0633",
    "email": "theool.milioni@gmail.com",
    "groupe_voyage": "duo",
    "nombre_voyageurs": 2,
    "destination": "Tokyo",
    ...
  }
}
```

### 4. Exécuter la pipeline CrewAI manuellement

Pour lancer la pipeline en ligne de commande sans passer par l'API :

```bash
python crew_pipeline_cli.py --input-file examples/traveller_persona_input.json
```

ou à partir d'un identifiant de questionnaire :

```bash
python crew_pipeline_cli.py --questionnaire-id <UUID>
```

Vous pouvez également forcer dynamiquement le provider et le modèle utilisés par
les agents CrewAI sans modifier la configuration globale :

```bash
python crew_pipeline_cli.py \
  --input-file examples/traveller_persona_input.json \
  --llm-provider openai \
  --model gpt-4.1-mini
```

La pipeline instancie désormais deux agents complémentaires : un architecte
d'insights qui produit l'analyse primaire et un challenger de type ChatGPT qui
raisonne explicitement avant de valider ou d'amender la première proposition.

> 💡 L'ancien raccourci (`python -m app.crew_pipeline`) reste disponible si le dossier
> du projet se trouve dans votre `PYTHONPATH` (par exemple en exécutant la commande
> depuis la racine du dépôt).

## Test Rapide

Un script de test est fourni:

```bash
python test_api.py
```

Ce script teste:

- ✅ Health check
- ✅ Récupération via POST
- ✅ Récupération via GET

## Structure du Projet

```
Travliaq-Agents/
├── app/
│   ├── api/
│   │   ├── main.py           # Point d'entrée FastAPI
│   │   └── routes.py         # Endpoints API
│   ├── services/
│   │   └── supabase_service.py  # Service PostgreSQL
│   ├── crew_pipeline/        # Pipeline CrewAI (à venir)
│   └── config.py             # Configuration centralisée
├── crew/
│   ├── agents.yaml           # Définition des agents
│   ├── tasks.yaml            # Définition des tâches
│   ├── crew.yaml             # Configuration CrewAI
│   └── tools.yaml            # Outils (vides pour l'instant)
├── tests/                    # Tests unitaires
├── output/                   # JSON générés
├── .env                      # Configuration (avec credentials)
├── requirements.txt          # Dépendances Python
└── test_api.py              # Script de test rapide
```

## Endpoints Disponibles

| Méthode | Endpoint                     | Description                          |
| ------- | ---------------------------- | ------------------------------------ |
| GET     | `/`                          | Informations de base                 |
| GET     | `/api/v1/health`             | Health check                         |
| POST    | `/api/v1/questionnaire`      | Récupérer questionnaire (body JSON)  |
| GET     | `/api/v1/questionnaire/{id}` | Récupérer questionnaire (path param) |

## Prochaines Étapes

1. ✅ API fonctionnelle avec récupération des questionnaires
2. ✅ Pipeline CrewAI pour générer les trips
3. ✅ Outputs structurés avec Pydantic
4. ✅ Observabilité et métriques de performance
5. 🔜 Stockage des trips générés dans Supabase
6. 🔜 Tests unitaires complets

## Best Practices Appliquées

### Outputs Structurés avec Pydantic

La pipeline utilise des modèles Pydantic pour garantir la qualité et la cohérence des outputs :

```python
from app.crew_pipeline.models import PersonaAnalysisOutput, PersonaChallengeOutput

# Les agents produisent automatiquement des outputs validés
# Définis dans agents.yaml :
# output_pydantic: app.crew_pipeline.models.PersonaAnalysisOutput
```

**Avantages** :

- Validation automatique des données
- Typage fort et autocomplete dans l'IDE
- Documentation intégrée des schémas
- Détection précoce des erreurs

### Observabilité et Métriques

Chaque exécution de la pipeline génère des métriques détaillées :

```bash
# Les métriques sont sauvegardées dans output/<run_id>/metrics.json
cat output/mon-run-abc123/metrics.json
```

**Métriques collectées** :

- Durée d'exécution totale et par agent
- Nombre de tokens utilisés
- Coût estimé (USD)
- Scores de qualité des outputs
- Erreurs et avertissements

### Gestion d'Erreurs Robuste

Les outils MCP incluent retry logic et timeout :

```yaml
# Configuration dans mcp_tools.py
MCP_TIMEOUT_SECONDS = 30  # Timeout par défaut
MCP_MAX_RETRIES = 3       # Nombre de tentatives
```

### Optimisations LLM

Configuration optimisée des agents pour contrôler les coûts :

```yaml
# Dans agents.yaml
max_iter: 15 # Limite d'itérations
memory: true # Mémoire contextuelle
reasoning: true # Raisonnement explicite
max_reasoning_attempts: 3 # Tentatives de raisonnement
```

## Logs

L'API affiche des logs détaillés:

```
2025-11-14 16:30:00 - INFO - 🚀 Démarrage de Travliaq-Agents API
2025-11-14 16:30:00 - INFO - 📊 Log level: INFO
2025-11-14 16:30:00 - INFO - 🔗 Supabase URL: https://cinbnmlfpffmyjmkwbco.supabase.co
2025-11-14 16:30:00 - INFO - 🗄️  PostgreSQL: db.cinbnmlfpffmyjmkwbco.supabase.co:5432
2025-11-14 16:30:05 - INFO - 📥 Requête reçue pour questionnaire: c92a18b0-...
2025-11-14 16:30:05 - INFO - ✅ Connexion PostgreSQL établie
2025-11-14 16:30:05 - INFO - ✅ Questionnaire récupéré: c92a18b0-...
```

## Troubleshooting

### ModuleNotFoundError: No module named 'app'

Si tu obtiens cette erreur, **n'utilise PAS** `python app/api/main.py` directement.

**Utilise plutôt:**

```bash
# Option recommandée
python run.py

# Ou
start.bat

# Ou
uvicorn app.api.main:app --reload
```

### Erreur de connexion PostgreSQL

Si vous obtenez une erreur de connexion:

```
❌ Erreur connexion PostgreSQL
```

Vérifiez:

1. Les credentials dans `.env`
2. Votre connexion internet
3. Les règles firewall Supabase

### Port 8000 déjà utilisé

Si le port 8000 est déjà pris, modifiez dans `.env`:

```
API_PORT=8001
```
