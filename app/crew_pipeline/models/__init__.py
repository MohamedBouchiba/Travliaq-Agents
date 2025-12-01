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
