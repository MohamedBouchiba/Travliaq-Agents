"""Normalisation déterministe des questionnaires avant passage aux agents."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Tuple


class NormalizationError(Exception):
    """Erreur bloquante lors de la normalisation."""


def _parse_date(value: Any) -> Tuple[Any, List[str]]:
    """
    Parse une date depuis différents formats et retourne ISO (YYYY-MM-DD).

    Formats supportés:
    - ISO: 2025-12-15, 2025/12/15
    - Européen: 15/12/2025, 15-12-2025, 15.12.2025
    - Américain: 12/15/2025 (ambiguë avec européen, testé en dernier)
    """
    warnings: List[str] = []
    if value in (None, "", "null"):
        return None, warnings
    if isinstance(value, datetime):
        return value.date().isoformat(), warnings
    if isinstance(value, str):
        # Nettoyer la chaîne
        value_clean = value.strip().replace("Z", "")

        # Liste des formats à essayer (ordre = priorité)
        formats = [
            "%Y-%m-%d",      # ISO: 2025-12-15 (format prioritaire)
            "%Y/%m/%d",      # ISO slash: 2025/12/15
            "%d/%m/%Y",      # Européen slash: 15/12/2025
            "%d-%m-%Y",      # Européen dash: 15-12-2025
            "%d.%m.%Y",      # Européen point: 15.12.2025
            "%m/%d/%Y",      # Américain: 12/15/2025 (ambiguë, testé en dernier)
        ]

        for fmt in formats:
            try:
                parsed = datetime.strptime(value_clean, fmt)
                iso_date = parsed.date().isoformat()
                # Log si conversion effectuée depuis format non-ISO
                if fmt != "%Y-%m-%d":
                    warnings.append(f"date convertie depuis {fmt}: {value} -> {iso_date}")
                return iso_date, warnings
            except ValueError:
                continue

        # Si aucun format ne fonctionne
        warnings.append(f"date invalide (aucun format reconnu): {value}")
        return None, warnings

    warnings.append(f"format inconnu pour la date: {value}")
    return None, warnings


def _compute_nights(depart: Any, retour: Any) -> Tuple[Any, List[str]]:
    warnings: List[str] = []
    if not depart or not retour:
        return None, warnings
    try:
        d1 = datetime.fromisoformat(str(depart)).date()
        d2 = datetime.fromisoformat(str(retour)).date()
        if d2 < d1:
            warnings.append("date_retour avant date_depart")
            return None, warnings
        return (d2 - d1).days, warnings
    except Exception:
        warnings.append("calcul nuits impossible (format date)")
        return None, warnings


def normalize_questionnaire(questionnaire: Dict[str, Any]) -> Dict[str, Any]:
    """Nettoie/normalise le questionnaire et calcule quelques métriques déterministes."""

    normalized = deepcopy(questionnaire)
    warnings: List[str] = []
    blocking_errors: List[str] = []

    # Dates ISO
    departure_iso, dep_warn = _parse_date(normalized.get("date_depart"))
    return_iso, ret_warn = _parse_date(normalized.get("date_retour"))
    warnings.extend(dep_warn + ret_warn)
    if departure_iso:
        normalized["date_depart"] = departure_iso
    if return_iso:
        normalized["date_retour"] = return_iso

    # Nights computation
    nights, nights_warn = _compute_nights(departure_iso, return_iso)
    warnings.extend(nights_warn)
    if nights is not None:
        normalized["nuits_exactes"] = nights

    # Travelers count safety
    try:
        travellers = int(normalized.get("nombre_voyageurs")) if normalized.get("nombre_voyageurs") is not None else None
        if travellers is not None and travellers <= 0:
            blocking_errors.append("nombre_voyageurs doit être > 0")
        normalized["nombre_voyageurs"] = travellers
    except Exception:
        warnings.append("nombre_voyageurs non convertible en entier")
        normalized["nombre_voyageurs"] = None

    # Budget sanity (string passthrough, no hallucination)
    budget = normalized.get("budget_par_personne")
    if budget in ("", None):
        normalized["budget_par_personne"] = None

    normalized_payload = {
        "questionnaire": normalized,
        "metadata": {
            "normalized_at": datetime.utcnow().isoformat() + "Z",
            "blocking_errors": blocking_errors,
            "warnings": warnings,
        },
    }

    if blocking_errors:
        raise NormalizationError("; ".join(blocking_errors))

    return normalized_payload
