"""Validation JSON Schema du trip final."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import jsonschema


class SchemaValidationError(Exception):
    """Erreur de validation JSON Schema."""


def validate_trip_schema(trip_payload: Dict[str, Any], schema_path: Optional[Path] = None) -> Tuple[bool, Optional[str]]:
    """Valide le payload final contre le schéma Draft-07."""

    if schema_path is None:
        schema_path = Path(__file__).resolve().parent.parent / "config" / "trip_schema.json"

    if not schema_path.exists():
        return False, f"Schéma introuvable: {schema_path}"

    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    try:
        jsonschema.validate(instance=trip_payload, schema=schema)
        return True, None
    except jsonschema.ValidationError as exc:
        return False, str(exc)
