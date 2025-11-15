# Travliaq-Agents API

API FastAPI + CrewAI pour la génération automatique de trips Travliaq.

## Architecture

```
API Endpoint → PostgreSQL (Supabase) → Récupération Questionnaire → CrewAI Pipeline → JSON Trip
```

## Installation

### 1. Cloner le projet

```bash
git clone <repo-url>
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

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| GET | `/` | Informations de base |
| GET | `/api/v1/health` | Health check |
| POST | `/api/v1/questionnaire` | Récupérer questionnaire (body JSON) |
| GET | `/api/v1/questionnaire/{id}` | Récupérer questionnaire (path param) |

## Prochaines Étapes

1. ✅ API fonctionnelle avec récupération des questionnaires
2. 🔜 Pipeline CrewAI pour générer les trips
3. 🔜 Validation JSON Schema
4. 🔜 Stockage des trips générés dans Supabase
5. 🔜 Tests unitaires complets

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