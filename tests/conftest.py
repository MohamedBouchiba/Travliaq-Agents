"""Configuration de tests: variables d'environnement minimales."""

import os


def pytest_configure():  # pragma: no cover - hook pytest
    os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")
    os.environ.setdefault("PG_HOST", "localhost")
    os.environ.setdefault("PG_DATABASE", "travliaq")
    os.environ.setdefault("PG_USER", "travliaq")
    os.environ.setdefault("PG_PASSWORD", "travliaq")
    os.environ.setdefault("OPENAI_API_KEY", "test-key")

