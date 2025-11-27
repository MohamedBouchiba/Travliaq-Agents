"""Modèles Pydantic pour les outputs structurés des agents CrewAI.

Ce module définit les schémas de sortie pour chaque agent de la pipeline,
suivant les best practices CrewAI pour les outputs structurés.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class PersonaAnalysisOutput(BaseModel):
    """Output structuré de l'agent traveller_insights_analyst.
    
    Analyse argumentée et structurée du voyageur basée sur le questionnaire
    et l'inférence persona.
    """
    
    persona_summary: str = Field(
        ...,
        description="Résumé synthétique du profil voyageur",
        min_length=10,
    )
    
    pros: List[str] = Field(
        default_factory=list,
        description="Points favorables identifiés dans le profil",
    )
    
    cons: List[str] = Field(
        default_factory=list,
        description="Points de vigilance ou risques potentiels",
    )
    
    critical_needs: List[str] = Field(
        default_factory=list,
        description="Besoins indispensables du voyageur",
    )
    
    non_critical_preferences: List[str] = Field(
        default_factory=list,
        description="Préférences de confort non bloquantes",
    )
    
    user_goals: List[str] = Field(
        default_factory=list,
        description="Objectifs explicites ou implicites du voyage",
    )
    
    narrative: str = Field(
        ...,
        description="Paragraphe narratif immersif décrivant le voyageur",
        min_length=50,
    )
    
    analysis_notes: str = Field(
        default="",
        description="Synthèse de la réflexion et du raisonnement",
    )
    
    class Config:
        """Configuration du modèle Pydantic."""
        json_schema_extra = {
            "example": {
                "persona_summary": "Voyageur aventurier recherchant l'authenticité",
                "pros": ["Budget flexible", "Ouvert aux expériences locales"],
                "cons": ["Contraintes de temps limitées"],
                "critical_needs": ["Vols directs", "Hébergement confortable"],
                "non_critical_preferences": ["Cuisine locale", "Activités outdoor"],
                "user_goals": ["Découvrir la culture locale", "Se ressourcer"],
                "narrative": "Jean est un voyageur curieux...",
                "analysis_notes": "Le profil indique une forte motivation...",
            }
        }


class PersonaChallengeOutput(BaseModel):
    """Output structuré de l'agent persona_quality_challenger.
    
    Challenge et validation de l'analyse initiale avec recommandations
    concrètes pour les travel designers.
    """
    
    persona_summary: str = Field(
        ...,
        description="Résumé du profil mis à jour après challenge",
        min_length=10,
    )
    
    pros: List[str] = Field(
        default_factory=list,
        description="Liste consolidée des points favorables",
    )
    
    cons: List[str] = Field(
        default_factory=list,
        description="Liste consolidée des points de vigilance",
    )
    
    critical_needs: List[str] = Field(
        default_factory=list,
        description="Besoins confirmés après validation",
    )
    
    non_critical_preferences: List[str] = Field(
        default_factory=list,
        description="Préférences validées",
    )
    
    user_goals: List[str] = Field(
        default_factory=list,
        description="Objectifs validés et affinés",
    )
    
    narrative: str = Field(
        ...,
        description="Récit affiné après challenge",
        min_length=50,
    )
    
    analysis_notes: str = Field(
        default="",
        description="Synthèse complète de l'analyse",
    )
    
    challenge_summary: str = Field(
        ...,
        description="Synthèse de ce que le challenge a apporté",
        min_length=20,
    )
    
    challenge_actions: List[str] = Field(
        default_factory=list,
        description="Actions concrètes à transmettre aux travel designers",
    )
    
    class Config:
        """Configuration du modèle Pydantic."""
        json_schema_extra = {
            "example": {
                "persona_summary": "Voyageur aventurier validé avec budget confirmé",
                "pros": ["Budget flexible vérifié", "Expérience voyage confirmée"],
                "cons": ["Contraintes familiales à prendre en compte"],
                "critical_needs": ["Vols directs confirmés", "Assurance annulation"],
                "non_critical_preferences": ["Guide local recommandé"],
                "user_goals": ["Immersion culturelle", "Repos et déconnexion"],
                "narrative": "Jean est un voyageur expérimenté...",
                "analysis_notes": "L'analyse a été validée avec quelques ajustements...",
                "challenge_summary": "Validation des hypothèses avec ajout de contraintes familiales",
                "challenge_actions": ["Proposer guide francophone", "Prévoir hébergement familial"],
            }
        }


class DestinationInfo(BaseModel):
    """Information sur une destination du voyage."""
    
    label: str = Field(
        ...,
        description="Type de destination: primary, secondary, etc.",
    )
    
    city: Optional[str] = Field(
        None,
        description="Ville de destination",
    )
    
    country: Optional[str] = Field(
        None,
        description="Pays de destination",
    )
    
    stay_nights: Optional[int] = Field(
        None,
        ge=0,
        description="Nombre de nuits prévues",
    )


class DateInfo(BaseModel):
    """Information sur les dates du voyage."""
    
    type: str = Field(
        ...,
        description="Type de dates: fixed ou flexible",
        pattern="^(fixed|flexible)$",
    )
    
    departure_dates: List[str] = Field(
        default_factory=list,
        description="Dates de départ possibles (YYYY-MM-DD)",
    )
    
    return_dates: List[str] = Field(
        default_factory=list,
        description="Dates de retour possibles (YYYY-MM-DD)",
    )
    
    duration_nights: Optional[int] = Field(
        None,
        ge=1,
        description="Durée en nuits",
    )


class TripSpecificationsOutput(BaseModel):
    """Output structuré de l'agent trip_specifications_architect.
    
    Spécifications techniques normalisées du voyage, prêtes pour
    les algorithmes de recherche.
    """
    
    normalized_trip_request: dict = Field(
        ...,
        description="Structure YAML/dict complète de la demande de voyage normalisée",
    )
    
    synthesis_notes: str = Field(
        default="",
        description="Notes sur la qualité des données entrantes",
    )
    
    class Config:
        """Configuration du modèle Pydantic."""
        json_schema_extra = {
            "example": {
                "normalized_trip_request": {
                    "user": {
                        "email": "user@example.com",
                        "preferred_language": "fr"
                    },
                    "travel_party": {
                        "group_type": "couple",
                        "travelers_count": 2,
                        "has_children": False,
                        "children": []
                    },
                    "trip_frame": {
                        "destinations": [
                            {
                                "label": "primary",
                                "city": "Tokyo",
                                "country": "Japan",
                                "stay_nights": 7
                            }
                        ]
                    }
                },
                "synthesis_notes": "Données complètes et cohérentes",
            }
        }


class PipelineMetrics(BaseModel):
    """Métriques d'exécution de la pipeline pour l'observabilité."""
    
    run_id: str = Field(
        ...,
        description="Identifiant unique de l'exécution",
    )
    
    total_duration_seconds: float = Field(
        ...,
        ge=0,
        description="Durée totale d'exécution en secondes",
    )
    
    agent_executions: List[dict] = Field(
        default_factory=list,
        description="Métriques par agent exécuté",
    )
    
    total_tokens_used: Optional[int] = Field(
        None,
        ge=0,
        description="Nombre total de tokens utilisés",
    )
    
    estimated_cost_usd: Optional[float] = Field(
        None,
        ge=0,
        description="Coût estimé en USD",
    )
    
    errors_count: int = Field(
        default=0,
        ge=0,
        description="Nombre d'erreurs rencontrées",
    )
    
    warnings_count: int = Field(
        default=0,
        ge=0,
        description="Nombre d'avertissements",
    )
