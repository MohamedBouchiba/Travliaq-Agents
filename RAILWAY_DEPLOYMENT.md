# Travliaq-Agents - Railway Deployment Guide

## Required Environment Variables

Pour que le service fonctionne correctement sur Railway, vous devez configurer les variables d'environnement suivantes dans les paramètres du projet Railway.

### Variables requises

#### Supabase (si utilisé)
```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
```

#### PostgreSQL (si utilisé)
```
PG_HOST=your-db-host
PG_DATABASE=postgres
PG_USER=postgres
PG_PASSWORD=your-password
PG_PORT=5432
PG_SSLMODE=require
```

#### OpenAI API Key (recommandé)
```
OPENAI_API_KEY=your-openai-key
```

### Variables optionnelles

#### Configuration API
```
API_HOST=0.0.0.0
API_PORT=8001
API_WORKERS=1
```

#### Configuration CrewAI
```
MODEL_PROVIDER=openai
MODEL_NAME=gpt-4o-mini
MAX_RPM=50
TEMPERATURE=0.3
MAX_ITER=5
VERBOSE=true
```

## Comment configurer sur Railway

1. Allez dans votre projet sur Railway
2. Sélectionnez le service `Travliaq-Agents`
3. Cliquez sur l'onglet "Variables"
4. Ajoutez les variables une par une
5. Cliquez sur "Deploy" pour redémarrer avec les nouvelles variables

## Note

Les variables Supabase et PostgreSQL sont maintenant optionnelles. Si elles ne sont pas définies, le service démarrera quand même, mais les fonctionnalités liées à la base de données ne seront pas disponibles.
