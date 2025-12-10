"""
Stratégie centralisée de calcul du nombre de steps.

Assure cohérence entre builder, agents, et templates.
"""
from typing import Dict


class StepCountStrategy:
    """
    Calcul standardisé du nombre de steps selon rythme.

    Usage:
        >>> StepCountStrategy.calculate(7, "relaxed")
        8
        >>> StepCountStrategy.calculate(7, "balanced")
        10
        >>> StepCountStrategy.calculate(7, "intense")
        17
    """

    # Multiplicateurs basés sur analyse des préférences utilisateur
    RHYTHM_MULTIPLIERS: Dict[str, float] = {
        "relaxed": 1.2,   # 1-2 steps/jour (privilégier 1)
        "balanced": 1.5,  # 1-2 steps/jour (mix)
        "intense": 2.5    # 2-3 steps/jour
    }

    @classmethod
    def calculate(cls, total_days: int, rhythm: str) -> int:
        """
        Calculer le nombre de steps (activités) selon la durée et le rythme.

        Args:
            total_days: Nombre de jours du voyage
            rhythm: Rythme du voyageur ("relaxed", "balanced", "intense")

        Returns:
            Nombre de steps à générer (minimum 1)

        Raises:
            ValueError: Si total_days <= 0

        Examples:
            >>> StepCountStrategy.calculate(7, "relaxed")
            8  # 7 × 1.2 = 8.4 → 8
            >>> StepCountStrategy.calculate(7, "balanced")
            10  # 7 × 1.5 = 10.5 → 10
            >>> StepCountStrategy.calculate(7, "intense")
            17  # 7 × 2.5 = 17.5 → 17
        """
        if total_days <= 0:
            raise ValueError(f"total_days must be positive, got {total_days}")

        multiplier = cls.RHYTHM_MULTIPLIERS.get(rhythm, 1.5)
        calculated = int(total_days * multiplier)

        return max(1, calculated)

    @classmethod
    def validate_rhythm(cls, rhythm: str) -> str:
        """
        Valider et normaliser le rythme.

        Args:
            rhythm: Rythme à valider

        Returns:
            Rythme normalisé (relaxed, balanced, ou intense)

        Raises:
            ValueError: Si rythme invalide
        """
        rhythm_lower = rhythm.lower().strip()

        if rhythm_lower not in cls.RHYTHM_MULTIPLIERS:
            valid = ", ".join(cls.RHYTHM_MULTIPLIERS.keys())
            raise ValueError(f"Invalid rhythm '{rhythm}'. Valid: {valid}")

        return rhythm_lower

    @classmethod
    def get_steps_per_day_range(cls, rhythm: str) -> str:
        """
        Obtenir la plage de steps/jour pour un rythme.

        Args:
            rhythm: Rythme du voyage

        Returns:
            String décrivant la plage (ex: "1-2", "2-3")
        """
        rhythm = cls.validate_rhythm(rhythm)

        ranges = {
            "relaxed": "1-2",
            "balanced": "1-2",
            "intense": "2-3"
        }

        return ranges.get(rhythm, "1-2")
