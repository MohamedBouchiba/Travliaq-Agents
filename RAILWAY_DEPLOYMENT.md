# Travliaq-Agents - Railway Deployment Guide

## Required Environment Variables

Pour que le service fonctionne correctement sur Railway, vous devez configurer les variables d'environnement suivantes dans les paramètres du projet Railway.

### Variables requises

#### PostgreSQL (Connection Pooler)
Utilisez les informations du Supabase Connection Pooler (Supavisor) pour supporter IPv4.

```
PG_HOST=aws-1-eu-west-3.pooler.supabase.com
PG_DATABASE=postgres
PG_USER=postgres.cinbnmlfpffmyjmkwbco
PG_PASSWORD=your-password
PG_PORT=6543
PG_SSLMODE=require
PG_POOL_MODE=transaction
```

#### Environment
Définissez l'environnement (development ou production).
```
ENVIRONMENT=production
```

#### OpenAI API Key
```
OPENAI_API_KEY=your-openai-key
```

### Variables optionnelles

#### Supabase (API)
```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
```

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
4. Ajoutez/Modifiez les variables ci-dessus
5. Cliquez sur "Deploy" pour redémarrer

## Note sur les environnements

Le projet supporte maintenant la gestion d'environnements via la variable `ENVIRONMENT`.
- `ENVIRONMENT=development` : Charge `.env` (local)
- `ENVIRONMENT=production` : Optimisé pour la prod (Railway)
