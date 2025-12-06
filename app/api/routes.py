"""Routes API pour Travliaq-Agents."""

import logging
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, status, BackgroundTasks
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


class PipelineStartedResponse(BaseModel):
    """Réponse immédiate quand la pipeline est lancée en arrière-plan."""
    status: str
    message: str
    questionnaire_id: str
    persona: str
    confidence: int


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


def run_pipeline_sync(
    questionnaire_data: Dict[str, Any],
    inference_dict: Dict[str, Any],
    questionnaire_id: str,
):
    """
    Exécute la pipeline CrewAI de manière synchrone.
    Cette fonction est appelée en arrière-plan.
    """
    run_id = None
    pipeline_status = "PENDING"
    trip_json = None
    persona_analysis = None
    
    try:
        logger.info(f"🚀 Pipeline lancée en arrière-plan pour: {questionnaire_id}")
        
        result = travliaq_crew_pipeline.run(
            questionnaire_data=questionnaire_data,
            persona_inference=inference_dict,
            payload_metadata={
                "questionnaire_id": questionnaire_id,
                "status": "ok",
            },
        )
        
        run_id = result.get('run_id', 'N/A')
        pipeline_status = "SUCCESS"
        trip_json = result.get("trip_json")
        persona_analysis = result.get("persona_analysis", {})
        
        logger.info(f"✅ Pipeline terminée pour: {questionnaire_id}")
        logger.info(f"📊 Run ID: {run_id}")
        
    except Exception as e:
        logger.error(f"❌ Erreur pipeline pour {questionnaire_id}: {e}")
        pipeline_status = "FAILED"
        import traceback
        traceback.print_exc()
    
    # ✅ TOUJOURS sauvegarder le trip summary (même en cas d'échec partiel)
    try:
        logger.info(f"💾 Sauvegarde trip summary pour: {questionnaire_id}")
        
        summary_id = supabase_service.save_trip_summary(
            questionnaire_id=questionnaire_id,
            questionnaire_data=questionnaire_data,
            persona_inference=inference_dict,
            persona_analysis=persona_analysis or {},
            trip_json=trip_json,
            run_id=run_id or f"{questionnaire_id}-unknown",
            pipeline_status=pipeline_status,
        )
        
        if summary_id:
            logger.info(f"✅ Trip summary sauvegardé: {summary_id}")
        else:
            logger.warning(f"⚠️ Trip summary non sauvegardé pour: {questionnaire_id}")
            
    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde trip summary: {e}")
        # Ne pas propager l'erreur, le pipeline principal est terminé


@router.post("/process", response_model=PipelineStartedResponse)
async def process_questionnaire(
    request: QuestionnaireRequest,
    background_tasks: BackgroundTasks,
):
    """
    Lance le traitement d'un questionnaire en arrière-plan.
    
    1. Récupère le questionnaire depuis Supabase
    2. Infère le persona rapidement
    3. Lance la pipeline CrewAI en arrière-plan
    4. Retourne immédiatement OK

    Args:
        request: Requête contenant l'ID du questionnaire

    Returns:
        Confirmation immédiate que la pipeline est lancée
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

        # Étape 2: Inférer le persona (rapide, on le fait en synchrone)
        logger.info("🧠 Inférence du persona...")
        inference_result = persona_engine.infer_persona(questionnaire_data)
        inference_dict = persona_engine.to_dict(inference_result)

        persona_name = inference_dict['persona']['principal']
        confidence = inference_dict['persona']['confiance']
        
        logger.info(f"✅ Persona inféré: {persona_name}")
        logger.info(f"📊 Confiance: {confidence}%")

        # Étape 3: Lancer la pipeline en arrière-plan (non-bloquant)
        logger.info("🚀 Lancement pipeline CrewAI en arrière-plan...")
        background_tasks.add_task(
            run_pipeline_sync,
            questionnaire_data,
            inference_dict,
            request.questionnaire_id,
        )

        # Étape 4: Retourner immédiatement
        return PipelineStartedResponse(
            status="ok",
            message="Pipeline lancée en arrière-plan",
            questionnaire_id=request.questionnaire_id,
            persona=persona_name,
            confidence=confidence,
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


@router.get("/process/{questionnaire_id}", response_model=PipelineStartedResponse)
async def process_questionnaire_by_path(
    questionnaire_id: str,
    background_tasks: BackgroundTasks,
):
    """
    Traite un questionnaire via path parameter (GET).
    Lance la pipeline en arrière-plan.

    Args:
        questionnaire_id: UUID du questionnaire

    Returns:
        Confirmation immédiate que la pipeline est lancée
    """
    return await process_questionnaire(
        QuestionnaireRequest(questionnaire_id=questionnaire_id),
        background_tasks,
    )