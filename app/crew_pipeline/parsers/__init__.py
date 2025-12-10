"""
Parsers pour extraire données structurées depuis outputs d'agents.
"""
from .agent_output_parser import (
    AgentOutputParser,
    FlightData,
    AccommodationData,
    BudgetData
)

__all__ = [
    "AgentOutputParser",
    "FlightData",
    "AccommodationData",
    "BudgetData"
]
