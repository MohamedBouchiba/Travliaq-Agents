"""Tests ciblés pour la CLI Crew Pipeline."""

from __future__ import annotations

import os

from app.crew_pipeline import __main__ as crew_cli


def test_apply_llm_overrides_sets_environment(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("MODEL", raising=False)

    crew_cli._apply_llm_overrides(provider="openai", model="gpt-4.1-mini")

    assert os.environ["LLM_PROVIDER"] == "openai"
    assert os.environ["MODEL"] == "gpt-4.1-mini"


def test_apply_llm_overrides_ignores_missing_values(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("MODEL", "gpt-4o-mini")

    crew_cli._apply_llm_overrides(provider=None, model=None)

    assert os.environ["LLM_PROVIDER"] == "groq"
    assert os.environ["MODEL"] == "gpt-4o-mini"
