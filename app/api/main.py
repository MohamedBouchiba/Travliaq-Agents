"""Point d'entrée principal de l'API Travliaq-Agents."""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.routes import router

# Configuration du logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestion du cycle de vie de l'application."""
    # Startup
    logger.info("🚀 Démarrage de Travliaq-Agents API")
    logger.info(f"📊 Log level: {settings.log_level}")
    logger.info(f"🔗 Supabase URL: {settings.supabase_url}")
    logger.info(f"🗄️  PostgreSQL: {settings.pg_host}:{settings.pg_port}")
    
    yield
    
    # Shutdown
    logger.info("👋 Arrêt de Travliaq-Agents API")


# Création de l'application FastAPI
app = FastAPI(
    title="Travliaq-Agents API",
    description="API pour la génération automatique de trips Travliaq via CrewAI",
    version="0.1.0",
    lifespan=lifespan
)

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # À restreindre en production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclusion des routes
app.include_router(router)


@app.get("/")
async def root():
    """Route racine de l'API."""
    return {
        "service": "Travliaq-Agents API",
        "version": "0.1.0",
        "status": "running",
        "docs": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
        log_level=settings.log_level.lower()
    )
