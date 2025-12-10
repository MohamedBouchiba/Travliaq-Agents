"""
Parser centralisé pour extraire données structurées depuis les outputs des agents.

Avantages :
- Logique d'extraction centralisée (DRY)
- Gestion cohérente des structures variables
- Tests unitaires faciles
- Réduction de la duplication de code
"""
from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class FlightData:
    """Données structurées des vols."""
    origin_city: str
    destination_city: str
    duration: str
    flight_type: str
    price: str

    @classmethod
    def from_agent_output(cls, agent_output: Dict[str, Any]) -> Optional['FlightData']:
        """
        Extraire flight data depuis l'output de flights_research.

        Gère les variations de structure :
        - flight_quotes.summary.*
        - flight_quotes.* (direct)

        Args:
            agent_output: Dict contenant la clé "flights_research"

        Returns:
            FlightData ou None si données manquantes
        """
        if not agent_output:
            return None

        flight_quotes = agent_output.get("flight_quotes", {})
        if not flight_quotes:
            return None

        # Essayer summary d'abord (structure préférée)
        summary = flight_quotes.get("summary", {})

        return cls(
            origin_city=summary.get("from", "") or flight_quotes.get("from", ""),
            destination_city=summary.get("to", "") or flight_quotes.get("to", ""),
            duration=summary.get("duration", "") or flight_quotes.get("duration", ""),
            flight_type=summary.get("type", "") or flight_quotes.get("type", ""),
            price=summary.get("price", "") or str(flight_quotes.get("total_price", ""))
        )


@dataclass
class AccommodationData:
    """Données structurées de l'hébergement."""
    hotel_name: str
    hotel_rating: float
    price: str

    @classmethod
    def from_agent_output(cls, agent_output: Dict[str, Any]) -> Optional['AccommodationData']:
        """
        Extraire accommodation data depuis accommodation_research.

        Args:
            agent_output: Dict contenant la clé "lodging_quotes"

        Returns:
            AccommodationData ou None si données manquantes
        """
        if not agent_output:
            return None

        lodging_quotes = agent_output.get("lodging_quotes", {})
        if not lodging_quotes:
            return None

        # Essayer recommended d'abord
        recommended = lodging_quotes.get("recommended", {})

        # Extraction avec fallbacks
        hotel_name = (
            recommended.get("hotel_name", "") or
            lodging_quotes.get("hotel_name", "")
        )

        hotel_rating = float(
            recommended.get("hotel_rating", 0) or
            lodging_quotes.get("rating", 0) or
            0
        )

        price = (
            recommended.get("price_display", "") or
            str(recommended.get("total_price", "")) or
            str(lodging_quotes.get("price", ""))
        )

        return cls(
            hotel_name=hotel_name,
            hotel_rating=hotel_rating,
            price=price
        )


@dataclass
class BudgetData:
    """Données structurées du budget."""
    total_price: str
    price_flights: str
    price_hotels: str
    price_transport: str
    price_activities: str

    @classmethod
    def from_agent_output(cls, agent_output: Dict[str, Any]) -> Optional['BudgetData']:
        """
        Extraire budget depuis budget_calculation.

        Gère les multiples structures possibles :
        - budget_summary.totals.*
        - budget_summary.breakdown.*
        - budget_summary directement

        Args:
            agent_output: Dict contenant la clé "budget_summary"

        Returns:
            BudgetData ou None si données manquantes
        """
        if not agent_output:
            return None

        budget_summary = agent_output.get("budget_summary", {})
        if not budget_summary:
            return None

        # Gestion des structures variées
        budget_data = budget_summary.get("budget_summary", budget_summary)
        totals = budget_data.get("totals", {}) if isinstance(budget_data, dict) else {}
        breakdown = budget_data.get("breakdown", {}) if isinstance(budget_data, dict) else {}

        # Extraction total avec fallbacks multiples
        total_price = (
            totals.get("grand_total") or
            totals.get("display") or
            budget_data.get("total_price") or
            budget_data.get("total_budget") or
            budget_data.get("estimated_total", "")
        )

        # Extraction détails avec fallbacks
        flights_data = breakdown.get("flights", {})
        price_flights = (
            flights_data.get("total") or
            budget_data.get("flight_cost") or
            budget_data.get("flights_cost", "")
        )

        hotels_data = breakdown.get("accommodation", {})
        price_hotels = (
            hotels_data.get("total") or
            budget_data.get("accommodation_cost") or
            budget_data.get("lodging_cost", "")
        )

        transport_data = breakdown.get("transport_local", {})
        price_transport = (
            transport_data.get("total") or
            budget_data.get("transport_cost") or
            budget_data.get("local_transport_cost", "")
        )

        activities_data = breakdown.get("activities", {})
        price_activities = (
            activities_data.get("total") or
            budget_data.get("activities_cost", "")
        )

        return cls(
            total_price=str(total_price) if total_price else "",
            price_flights=str(price_flights) if price_flights else "",
            price_hotels=str(price_hotels) if price_hotels else "",
            price_transport=str(price_transport) if price_transport else "",
            price_activities=str(price_activities) if price_activities else ""
        )


class AgentOutputParser:
    """
    Parser centralisé pour tous les outputs d'agents.

    Usage:
        >>> parser = AgentOutputParser()
        >>> flight_data = parser.extract_flights(phase2_output)
        >>> print(flight_data.origin_city)
        'Paris'
    """

    @staticmethod
    def extract_flights(phase2_output: Dict[str, Any]) -> Optional[FlightData]:
        """
        Extraire données vols depuis PHASE2.

        Args:
            phase2_output: Dict avec clé "flights_research"

        Returns:
            FlightData ou None

        Example:
            >>> output = {"flights_research": {"flight_quotes": {"summary": {...}}}}
            >>> flight_data = AgentOutputParser.extract_flights(output)
        """
        flights_research = phase2_output.get("flights_research", {})
        return FlightData.from_agent_output(flights_research)

    @staticmethod
    def extract_accommodation(phase2_output: Dict[str, Any]) -> Optional[AccommodationData]:
        """
        Extraire données hébergement depuis PHASE2.

        Args:
            phase2_output: Dict avec clé "accommodation_research"

        Returns:
            AccommodationData ou None
        """
        accommodation_research = phase2_output.get("accommodation_research", {})
        return AccommodationData.from_agent_output(accommodation_research)

    @staticmethod
    def extract_budget(phase3_output: Dict[str, Any]) -> Optional[BudgetData]:
        """
        Extraire données budget depuis PHASE3.

        Args:
            phase3_output: Dict avec clé "budget_calculation"

        Returns:
            BudgetData ou None
        """
        budget_calculation = phase3_output.get("budget_calculation", {})
        return BudgetData.from_agent_output(budget_calculation)
