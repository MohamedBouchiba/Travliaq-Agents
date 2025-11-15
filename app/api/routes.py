"""Routes API pour Travliaq-Agents."""

import logging
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.services.supabase_service import supabase_service
from app.services.persona_inference_service import persona_engine
from app.crew_pipeline import travliaq_crew_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["travliaq"])


class QuestionnaireRequest(BaseModel):
    """Requête pour traiter un questionnaire."""
    questionnaire_id: str = Field(..., description="UUID du questionnaire")


class TravliaqResponse(BaseModel):
    """Réponse complète du traitement."""

    status: str
    pipeline_run_id: str
    questionnaire_id: str
    questionnaire_data: Dict[str, Any]
    persona_inference: Dict[str, Any]
    persona_analysis: Dict[str, Any]


class StatusResponse(BaseModel):
    """Réponse de statut simple."""
    status: str
    message: str


@router.get("/health", response_model=StatusResponse)
async def health_check():
    """
    Vérifie que l'API et la connexion PostgreSQL fonctionnent.

    Returns:
        Status de santé du service
    """
    try:
        db_ok = supabase_service.check_connection()

        if not db_ok:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database connection failed"
            )

        return StatusResponse(
            status="ok",
            message="Service is healthy"
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Health check failed: {str(e)}"
        )


@router.post("/process", response_model=TravliaqResponse)
async def process_questionnaire(request: QuestionnaireRequest):
    """
    Traite un questionnaire complet:
    1. Récupère depuis Supabase
    2. Infère le persona
    3. Retourne tout en JSON (en mémoire)

    Args:
        request: Requête contenant l'ID du questionnaire

    Returns:
        Questionnaire + Inférence de persona en JSON

    Raises:
        HTTPException: Si le questionnaire n'existe pas ou erreur de traitement
    """
    try:
        logger.info(f"📥 Traitement questionnaire: {request.questionnaire_id}")

        # Étape 1: Récupérer le questionnaire
        logger.info("📊 Récupération depuis Supabase...")
        questionnaire_data = supabase_service.get_questionnaire_by_id(request.questionnaire_id)

        if not questionnaire_data:
            logger.warning(f"⚠️  Questionnaire non trouvé: {request.questionnaire_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Questionnaire not found: {request.questionnaire_id}"
            )

        logger.info("✅ Questionnaire récupéré")

        # Étape 2: Inférer le persona
        logger.info("🧠 Inférence du persona...")
        inference_result = persona_engine.infer_persona(questionnaire_data)
        inference_dict = persona_engine.to_dict(inference_result)

        logger.info(f"✅ Persona inféré: {inference_dict['persona']['principal']}")
        logger.info(f"📊 Confiance: {inference_dict['persona']['confiance']}% ({inference_dict['persona']['niveau']})")

        # Étape 3: Analyse approfondie via CrewAI
        logger.info("🧠 Analyse approfondie via CrewAI...")
        persona_analysis_payload = travliaq_crew_pipeline.run(
            questionnaire_data=questionnaire_data,
            persona_inference=inference_dict,
            payload_metadata={
                "questionnaire_id": request.questionnaire_id,
                "status": "ok",
            },
        )

        logger.info("✅ Analyse CrewAI terminée")

        # Retourner le tout en JSON (en mémoire)
        return TravliaqResponse(
            status=persona_analysis_payload.get("status", "ok"),
            pipeline_run_id=persona_analysis_payload["run_id"],
            questionnaire_id=persona_analysis_payload.get(
                "questionnaire_id", request.questionnaire_id
            ),
            questionnaire_data=persona_analysis_payload["questionnaire_data"],
            persona_inference=persona_analysis_payload["persona_inference"],
            persona_analysis=persona_analysis_payload["persona_analysis"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors du traitement: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Processing error: {str(e)}"
        )


@router.get("/process/{questionnaire_id}", response_model=TravliaqResponse)
async def process_questionnaire_by_path(questionnaire_id: str):
    """
    Traite un questionnaire via path parameter (GET).

    Args:
        questionnaire_id: UUID du questionnaire

    Returns:
        Questionnaire + Inférence de persona en JSON
    """
    return await process_questionnaire(QuestionnaireRequest(questionnaire_id=questionnaire_id))