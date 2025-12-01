"""Modèles Pydantic pour le System Contract."""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Literal
from datetime import datetime


class TimingGrid(BaseModel):
    """Grille de recherche temporelle."""
    request_type: Literal["FIXED", "FLEXIBLE_RANGE", "FLEXIBLE_MONTH"]
    duration_min_nights: int = Field(ge=1)
    duration_max_nights: int = Field(ge=1)
    departure_dates_whitelist: List[str]  # Format YYYY-MM-DD
    return_dates_whitelist: List[str] = Field(default_factory=list)


class Geography(BaseModel):
    """Géographie du voyage."""
    origin_iata: str = Field(min_length=3, max_length=3)
    origin_city: str
    destination_is_defined: bool
    destination_city: Optional[str] = None
    destination_country: Optional[str] = None
    discovery_climate_zones: List[str] = Field(default_factory=list)
    discovery_regions: List[str] = Field(default_factory=list)
    excluded_tags: List[str] = Field(default_factory=list)


class Financials(BaseModel):
    """Budget et contraintes financières."""
    currency: str = Field(default="EUR")
    total_hard_cap: int = Field(gt=0)
    total_soft_cap: int = Field(gt=0)


class FlightSpecs(BaseModel):
    """Spécifications vols."""
    cabin_class: Literal["ECONOMY", "BUSINESS", "FIRST"] = "ECONOMY"
    luggage_policy: Literal["CARRY_ON", "CHECKED"] = "CHECKED"
    stopover_tolerance: Literal["0", "1", "2+"] = "2+"


class AccommodationSpecs(BaseModel):
    """Spécifications hébergement."""
    types_allowed: List[str] = Field(default_factory=list)
    min_rating_10: float = Field(ge=0, le=10, default=7.0)
    required_amenities: List[str] = Field(default_factory=list)
    location_vibe: str = "city_center"


class ExperienceSpecs(BaseModel):
    """Spécifications expérience."""
    pace: Literal["RELAXED", "BALANCED", "INTENSE"] = "BALANCED"
    interest_vectors: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)


class Specifications(BaseModel):
    """Spécifications techniques complètes."""
    flights: FlightSpecs = Field(default_factory=FlightSpecs)
    accommodation: AccommodationSpecs = Field(default_factory=AccommodationSpecs)
    experience: ExperienceSpecs = Field(default_factory=ExperienceSpecs)


class UserIntelligence(BaseModel):
    """Contexte intelligent de l'utilisateur."""
    email: str
    narrative_summary: str
    feasibility_status: Literal["VALID", "WARNING", "CRITICAL"] = "VALID"
    feasibility_alerts: List[str] = Field(default_factory=list)


class Meta(BaseModel):
    """Métadonnées du contrat."""
    request_id: str
    user_id: str
    timestamp: datetime
    source_version: str = "production_v5"


class SystemContract(BaseModel):
    """Contrat système complet (Phase 1 → Phase 2)."""
    meta: Meta
    user_intelligence: UserIntelligence
    timing: TimingGrid
    geography: Geography
    financials: Financials
    specifications: Specifications

    class Config:
        json_schema_extra = {
            "example": {
                "meta": {
                    "request_id": "uuid-here",
                    "user_id": "user-uuid",
                    "timestamp": "2025-12-01T00:00:00Z",
                    "source_version": "production_v5"
                }
            }
        }


# --- Outputs structurés des agents CrewAI (Phase 1) ---


class PersonaAnalysisOutput(BaseModel):
    """Analyse structurée du voyageur produite par l'analyste."""

    persona_summary: str = Field(
        ...,
        description="Résumé synthétique du profil voyageur",
        min_length=10,
    )

    pros: List[str] = Field(default_factory=list, description="Points favorables")
    cons: List[str] = Field(default_factory=list, description="Points de vigilance")
    critical_needs: List[str] = Field(default_factory=list, description="Besoins indispensables")
    non_critical_preferences: List[str] = Field(default_factory=list, description="Préférences non bloquantes")
    user_goals: List[str] = Field(default_factory=list, description="Objectifs explicites ou implicites")

    narrative: str = Field(
        ...,
        description="Paragraphe narratif immersif décrivant le voyageur",
        min_length=50,
    )

    analysis_notes: str = Field(default="", description="Notes de raisonnement")


class PersonaChallengeOutput(BaseModel):
    """Version challengée de l'analyse persona."""

    persona_summary: str = Field(
        ...,
        description="Résumé du profil après challenge",
        min_length=10,
    )

    pros: List[str] = Field(default_factory=list, description="Points favorables consolidés")
    cons: List[str] = Field(default_factory=list, description="Points de vigilance consolidés")
    critical_needs: List[str] = Field(default_factory=list, description="Besoins confirmés")
    non_critical_preferences: List[str] = Field(default_factory=list, description="Préférences validées")
    user_goals: List[str] = Field(default_factory=list, description="Objectifs affinés")

    narrative: str = Field(
        ...,
        description="Récit affiné après challenge",
        min_length=50,
    )

    analysis_notes: str = Field(default="", description="Notes de synthèse")
    challenge_summary: str = Field(
        ...,
        description="Résumé des apports du challenge",
        min_length=20,
    )
    challenge_actions: List[str] = Field(default_factory=list, description="Actions concrètes proposées")


class DestinationInfo(BaseModel):
    """Information sur une destination du voyage."""

    label: str = Field(..., description="Type de destination: primary, secondary, etc.")
    city: Optional[str] = Field(None, description="Ville de destination")
    country: Optional[str] = Field(None, description="Pays de destination")
    stay_nights: Optional[int] = Field(None, ge=0, description="Nombre de nuits prévues")


class DateInfo(BaseModel):
    """Information sur les dates du voyage."""

    type: str = Field(..., description="Type de dates: fixed ou flexible", pattern="^(fixed|flexible)$")
    departure_dates: List[str] = Field(default_factory=list, description="Dates de départ possibles (YYYY-MM-DD)")
    return_dates: List[str] = Field(default_factory=list, description="Dates de retour possibles (YYYY-MM-DD)")
    duration_nights: Optional[int] = Field(None, ge=1, description="Durée en nuits")


class TripSpecificationsOutput(BaseModel):
    """Spécifications normalisées du voyage produites par l'architecte."""

    normalized_trip_request: dict = Field(..., description="Payload normalisé complet")
    synthesis_notes: str = Field(default="", description="Notes sur la qualité des données")


class PipelineMetrics(BaseModel):
    """Métriques d'exécution de la pipeline pour l'observabilité."""

    run_id: str = Field(..., description="Identifiant unique de l'exécution")
    total_duration_seconds: float = Field(..., ge=0, description="Durée totale en secondes")
    agent_executions: List[dict] = Field(default_factory=list, description="Métriques par agent")
    total_tokens_used: Optional[int] = Field(None, ge=0, description="Tokens utilisés")
    estimated_cost_usd: Optional[float] = Field(None, ge=0, description="Coût estimé")
    errors_count: int = Field(default=0, ge=0, description="Nombre d'erreurs")
    warnings_count: int = Field(default=0, ge=0, description="Nombre d'avertissements")


__all__ = [
    "AccommodationSpecs",
    "DateInfo",
    "DestinationInfo",
    "ExperienceSpecs",
    "Financials",
    "FlightSpecs",
    "Geography",
    "Meta",
    "PersonaAnalysisOutput",
    "PersonaChallengeOutput",
    "PipelineMetrics",
    "Specifications",
    "SystemContract",
    "TimingGrid",
    "TripSpecificationsOutput",
    "UserIntelligence",
]
