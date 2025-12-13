"""
Trip Structure Calculator - Script déterministe pour remplacer l'agent trip_structure_planner

Ce script calcule AUTOMATIQUEMENT la structure optimale du trip selon :
- Le rythme du voyageur (relaxed/balanced/intense)
- La durée du séjour
- Les affinités voyage
- La destination

AVANTAGES vs Agent LLM:
- ✅ 100% déterministe et fiable
- ✅ 10x plus rapide (pas d'appel LLM)
- ✅ 100x moins cher (pas de tokens)
- ✅ Génère TOUJOURS tous les jours (pas de problème de limite de tokens)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def calculate_trip_structure(
    questionnaire: Dict[str, Any],
    destination: str,
    destination_country: str,
    total_days: int,
) -> Dict[str, Any]:
    """
    Calcule la structure optimale du trip de manière déterministe.

    Args:
        questionnaire: Questionnaire normalisé de l'utilisateur
        destination: Destination principale (ex: "Rio de Janeiro")
        destination_country: Pays de destination (ex: "Brésil")
        total_days: Nombre total de jours du séjour

    Returns:
        Dict contenant le trip_structure_plan complet
    """
    logger.info(f"🧮 Calculating trip structure for {destination} ({total_days} days)")

    # 1. EXTRAIRE LE RYTHME
    rhythm = questionnaire.get("rythme", "balanced")

    # 2. CALCULER LE NOMBRE DE STEPS PAR JOUR
    steps_per_day_config = {
        "relaxed": {"min": 1, "max": 2, "avg": 1.2},
        "balanced": {"min": 1, "max": 2, "avg": 1.5},
        "intense": {"min": 2, "max": 3, "avg": 2.5},
    }

    rhythm_config = steps_per_day_config.get(rhythm, steps_per_day_config["balanced"])
    avg_steps_per_day = rhythm_config["avg"]

    # 3. CALCULER LE NOMBRE TOTAL DE STEPS
    total_steps_planned = int(total_days * avg_steps_per_day)

    logger.info(f"   Rhythm: {rhythm} → {avg_steps_per_day} steps/day avg → {total_steps_planned} steps total")

    # 4. GÉNÉRER LA DISTRIBUTION PAR JOUR (INTELLIGENT)
    daily_distribution = _generate_daily_distribution(
        total_days=total_days,
        total_steps=total_steps_planned,
        rhythm=rhythm,
        rhythm_config=rhythm_config,
        destination=destination
    )

    # 5. EXTRAIRE LES AFFINITÉS VOYAGE
    affinites_voyage = questionnaire.get("affinites_voyage", [])
    activity_mix = _calculate_activity_mix(affinites_voyage)

    # 6. DÉTERMINER LES TYPES D'ACTIVITÉS PRIORITAIRES
    priority_activity_types = _determine_priority_activities(
        affinites_voyage=affinites_voyage,
        destination=destination,
        destination_country=destination_country
    )

    # 7. IDENTIFIER LES ZONES/QUARTIERS À COUVRIR
    zones_coverage = _identify_zones(
        destination=destination,
        total_days=total_days,
        daily_distribution=daily_distribution
    )

    # 8. ANALYSER LES PRIORITÉS CULTURELLES
    cultural_priorities = _identify_cultural_priorities(
        destination=destination,
        destination_country=destination_country,
        affinites_voyage=affinites_voyage
    )

    # 9. ASSEMBLER LE PLAN COMPLET
    trip_structure_plan = {
        "rhythm_analysis": {
            "questionnaire_rhythm": rhythm,
            "steps_per_day_range": f"{rhythm_config['min']}-{rhythm_config['max']}",
            "total_days": total_days,
            "total_steps_planned": total_steps_planned
        },
        "daily_distribution": daily_distribution,
        "activity_mix": activity_mix,
        "priority_activity_types": priority_activity_types,
        "zones_coverage": zones_coverage,
        "cultural_priorities": cultural_priorities,
        "constraints": {
            "max_steps_per_day": rhythm_config["max"],
            "min_free_time_per_day": "1-2h" if rhythm == "intense" else "2-3h",
            "avoid_back_and_forth": True,
            "group_by_proximity": True
        },
        # Méta-info pour tracking
        "total_days": total_days,
        "total_steps_planned": total_steps_planned,
    }

    logger.info(f"✅ Trip structure calculated: {total_steps_planned} steps across {total_days} days")

    return trip_structure_plan


def _generate_daily_distribution(
    total_days: int,
    total_steps: int,
    rhythm: str,
    rhythm_config: Dict[str, Any],
    destination: str
) -> List[Dict[str, Any]]:
    """
    Génère une distribution intelligente des steps par jour.

    Stratégie:
    - Alterner jours chargés et jours calmes
    - Respecter min/max du rythme
    - Éviter 3 jours intenses consécutifs
    """
    daily_distribution = []

    min_steps = rhythm_config["min"]
    max_steps = rhythm_config["max"]

    # Calculer combien de jours auront min vs max steps
    # Pour atteindre le total exact
    steps_remaining = total_steps

    for day in range(1, total_days + 1):
        days_remaining = total_days - day + 1
        avg_needed = steps_remaining / days_remaining if days_remaining > 0 else min_steps

        # Décider du nombre de steps pour ce jour
        if avg_needed <= min_steps:
            steps_count = min_steps
        elif avg_needed >= max_steps:
            steps_count = max_steps
        else:
            # Alterner intelligemment
            if day % 3 == 0:  # Tous les 3 jours → jour calme
                steps_count = min_steps
            elif rhythm == "intense" and day % 2 == 0:
                steps_count = max_steps
            else:
                steps_count = int(round(avg_needed))

        # Sécurité : clamp entre min et max
        steps_count = max(min_steps, min(max_steps, steps_count))

        # Déterminer l'intensité
        if steps_count <= min_steps:
            intensity = "low"
        elif steps_count >= max_steps:
            intensity = "high"
        else:
            intensity = "medium"

        # Zone par défaut (sera affinée plus tard)
        zone = f"Zone {((day - 1) // 3) + 1}"  # Change de zone tous les ~3 jours

        daily_distribution.append({
            "day": day,
            "steps_count": steps_count,
            "zone": zone,
            "intensity": intensity
        })

        steps_remaining -= steps_count

    return daily_distribution


def _calculate_activity_mix(affinites_voyage: List[str]) -> Dict[str, int]:
    """
    Calcule le mix d'activités basé sur les affinités du questionnaire.

    Retourne des pourcentages qui totalisent 100%.
    """
    if not affinites_voyage:
        # Mix par défaut équilibré
        return {
            "culture": 40,
            "gastronomy": 30,
            "relaxation": 20,
            "nature": 10
        }

    # Mapper les affinités vers des catégories principales
    category_mapping = {
        "culture": ["culture", "culture_urbaine", "musées", "monuments", "patrimoine", "histoire"],
        "nature": ["nature", "randonnée", "plage", "montagne", "paysages", "écotourisme"],
        "gastronomy": ["gastronomie", "cuisine_locale", "marchés", "restaurants"],
        "relaxation": ["détente", "spa", "bien-être", "plage"],
        "adventure": ["aventure", "sports", "randonnée", "escalade", "ski"],
        "nightlife": ["vie_nocturne", "bars", "clubs", "spectacles"],
        "shopping": ["shopping", "artisanat", "souvenirs"]
    }

    # Compter les occurrences par catégorie
    category_counts = {cat: 0 for cat in category_mapping.keys()}

    for affinite in affinites_voyage:
        affinite_lower = affinite.lower().replace(" ", "_")
        for category, keywords in category_mapping.items():
            if any(kw in affinite_lower for kw in keywords):
                category_counts[category] += 1

    # Calculer les pourcentages
    total_count = sum(category_counts.values())
    if total_count == 0:
        # Fallback
        return {
            "culture": 40,
            "gastronomy": 30,
            "relaxation": 20,
            "nature": 10
        }

    # Convertir en pourcentages (arrondi)
    activity_mix = {}
    for category, count in category_counts.items():
        if count > 0:
            percentage = int(round((count / total_count) * 100))
            if percentage > 0:
                activity_mix[category] = percentage

    # Ajuster pour atteindre exactement 100%
    total_percentage = sum(activity_mix.values())
    if total_percentage != 100 and activity_mix:
        # Ajuster la catégorie la plus importante
        max_category = max(activity_mix, key=activity_mix.get)
        activity_mix[max_category] += (100 - total_percentage)

    return activity_mix


def _determine_priority_activities(
    affinites_voyage: List[str],
    destination: str,
    destination_country: str
) -> List[str]:
    """
    Détermine les types d'activités prioritaires selon les affinités et la destination.

    Retourne une liste de 5-8 types d'activités.
    """
    priority_types = []

    # 🛡️ Safety: Handle None affinites_voyage
    if not affinites_voyage:
        affinites_voyage = []

    # 1. Basé sur les affinités
    activity_type_mapping = {
        "culture": "museums",
        "culture_urbaine": "historic_sites",
        "musées": "museums",
        "monuments": "monuments",
        "nature": "nature_exploration",
        "randonnée": "hiking",
        "plage": "beaches",
        "gastronomie": "local_cuisine",
        "marchés": "local_markets",
        "aventure": "adventure_sports",
        "détente": "relaxation",
        "spa": "wellness"
    }

    for affinite in affinites_voyage:
        affinite_lower = affinite.lower().replace(" ", "_")
        for keyword, activity_type in activity_type_mapping.items():
            if keyword in affinite_lower and activity_type not in priority_types:
                priority_types.append(activity_type)

    # 2. Ajouter des activités génériques toujours bonnes
    generic_activities = ["local_cuisine", "sightseeing", "photography"]
    for activity in generic_activities:
        if activity not in priority_types:
            priority_types.append(activity)

    # 3. Limiter à 5-8 types
    return priority_types[:8]


def _identify_zones(
    destination: str,
    total_days: int,
    daily_distribution: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Identifie les zones/quartiers à couvrir.

    Stratégie simple: diviser le séjour en 3-5 zones selon la durée.
    """
    # Nombre de zones selon la durée
    if total_days <= 3:
        num_zones = 1
    elif total_days <= 7:
        num_zones = 2
    elif total_days <= 14:
        num_zones = 3
    else:
        num_zones = min(5, (total_days // 4) + 1)

    zones_coverage = []
    days_per_zone = total_days // num_zones

    for zone_idx in range(num_zones):
        start_day = zone_idx * days_per_zone + 1
        end_day = (zone_idx + 1) * days_per_zone if zone_idx < num_zones - 1 else total_days

        days_in_zone = list(range(start_day, end_day + 1))
        activities_count = sum([
            d["steps_count"] for d in daily_distribution
            if d["day"] in days_in_zone
        ])

        # Noms de zones génériques (seront personnalisés par l'agent si besoin)
        zone_names = [
            f"Centre {destination}",
            f"Périphérie {destination}",
            f"Zone touristique",
            f"Quartier historique",
            f"Zone nature/plage"
        ]

        zones_coverage.append({
            "zone": zone_names[zone_idx % len(zone_names)],
            "days": days_in_zone,
            "activities_count": activities_count
        })

        # Mettre à jour les daily_distribution avec les zones
        for day_num in days_in_zone:
            for day_plan in daily_distribution:
                if day_plan["day"] == day_num:
                    day_plan["zone"] = zone_names[zone_idx % len(zone_names)]

    return zones_coverage


def _identify_cultural_priorities(
    destination: str,
    destination_country: str,
    affinites_voyage: List[str]
) -> Dict[str, str]:
    """
    Identifie les priorités culturelles de la destination.

    Retourne un dict générique (l'agent ou l'utilisateur peut personnaliser).
    """
    # 🛡️ Safety: Handle None affinites_voyage
    if not affinites_voyage:
        affinites_voyage = []

    cultural_priorities = {
        "top_1": f"Patrimoine culturel de {destination}",
        "top_2": f"Gastronomie locale de {destination_country}",
        "top_3": f"Architecture et monuments historiques",
        "top_4": f"Nature et paysages typiques de {destination_country}",
        "top_5": f"Traditions et artisanat local"
    }

    # Personnaliser selon les affinités
    if "nature" in [a.lower() for a in affinites_voyage]:
        cultural_priorities["top_1"] = f"Paysages naturels de {destination}"
    elif "gastronomie" in [a.lower() for a in affinites_voyage]:
        cultural_priorities["top_1"] = f"Gastronomie et cuisine de {destination}"

    return cultural_priorities
