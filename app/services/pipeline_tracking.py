"""
Service de tracking de pipeline simplifié.

Met à jour trip_summaries.pipeline_status et trip_summaries.trip_code
via supabase_service (qui gère déjà tout).
"""

import logging

logger = logging.getLogger(__name__)


class PipelineTrackingService:
    """Service simplifié - délègue tout à supabase_service.save_trip_summary()."""

    def mark_pipeline_success(
        self,
        questionnaire_id: str,
        trip_code: str,
        persona: str = None,  # noqa: ARG002
    ) -> bool:
        """
        Marque une pipeline comme SUCCESS.

        Note: La vraie mise à jour est faite par save_trip_summary()
        Cette méthode existe juste pour compatibilité.

        Args:
            questionnaire_id: UUID du questionnaire
            trip_code: Code du trip généré
            persona: Persona (ignoré, déjà dans save_trip_summary)

        Returns:
            True (toujours succès, le vrai tracking est dans save_trip_summary)
        """
        logger.debug(f"✅ Pipeline tracked as SUCCESS for {questionnaire_id[:8]}... → {trip_code}")
        return True

    def mark_pipeline_failed(
        self,
        questionnaire_id: str,
        error: str,
    ) -> bool:
        """
        Marque une pipeline comme FAILED.

        Note: save_trip_summary() gère déjà pipeline_status=FAILED

        Args:
            questionnaire_id: UUID du questionnaire
            error: Message d'erreur

        Returns:
            True
        """
        logger.debug(f"❌ Pipeline tracked as FAILED for {questionnaire_id[:8]}...: {error}")
        return True

    def mark_pipeline_running(
        self,
        questionnaire_id: str,
        run_id: str,  # noqa: ARG002
        persona: str = None,  # noqa: ARG002
    ) -> bool:
        """
        Marque une pipeline comme RUNNING.

        Note: Non utilisé car save_trip_summary() est appelé à la fin

        Args:
            questionnaire_id: UUID du questionnaire
            run_id: ID du run
            persona: Persona

        Returns:
            True
        """
        logger.debug(f"🔄 Pipeline tracked as RUNNING for {questionnaire_id[:8]}...")
        return True


# Instance singleton pour réutilisation
_tracking_service = None


def get_tracking_service() -> PipelineTrackingService:
    """Récupérer l'instance singleton du service de tracking."""
    global _tracking_service
    if _tracking_service is None:
        _tracking_service = PipelineTrackingService()
    return _tracking_service
