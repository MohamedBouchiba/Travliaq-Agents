import httpx
import pytest

from app.services.country_context_service import (
    build_country_context,
    fetch_public_holidays,
    fetch_unesco_world_heritage_sites,
)


def test_fetch_public_holidays_normalizes_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "2026/FR" in request.url.path
        return httpx.Response(
            status_code=200,
            json=[
                {
                    "date": "2026-01-01",
                    "localName": "Nouvel An",
                    "name": "New Year's Day",
                    "countryCode": "FR",
                    "global": True,
                    "counties": None,
                }
            ],
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        holidays = fetch_public_holidays("fr", 2026, client=client)

    assert holidays == [
        {
            "date": "2026-01-01",
            "local_name": "Nouvel An",
            "name": "New Year's Day",
            "country_code": "FR",
            "global": True,
            "counties": [],
        }
    ]


def test_fetch_public_holidays_handles_failure():
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    with httpx.Client(transport=transport) as client:
        holidays = fetch_public_holidays("US", 2026, client=client)

    assert holidays == []


def test_fetch_unesco_world_heritage_sites_normalizes_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["refine"] == "iso_code:FRA"
        return httpx.Response(
            status_code=200,
            json={
                "results": [
                    {
                        "site": "Mont-Saint-Michel and its Bay",
                        "states_name_en": "France",
                        "iso_code": "FRA",
                        "region_en": "Europe and North America",
                        "category": "Cultural",
                        "latitude": 48.636,
                        "longitude": -1.511,
                        "date_inscribed": 1979,
                        "justification": "Unique testimony to medieval society",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        sites = fetch_unesco_world_heritage_sites("fra", client=client)

    assert sites == [
        {
            "name": "Mont-Saint-Michel and its Bay",
            "country": "France",
            "iso_code": "FRA",
            "region": "Europe and North America",
            "category": "Cultural",
            "latitude": 48.636,
            "longitude": -1.511,
            "year_inscribed": 1979,
            "justification": "Unique testimony to medieval society",
        }
    ]


def test_build_country_context_aggregates(monkeypatch):
    monkeypatch.setattr(
        "app.services.country_context_service.fetch_public_holidays",
        lambda country_code, year=2026, client=None: [
            {"date": "2026-01-01", "name": "New Year's Day"}
        ],
    )
    monkeypatch.setattr(
        "app.services.country_context_service.fetch_unesco_world_heritage_sites",
        lambda country_code, client=None: [
            {"name": "Test Heritage"}
        ],
    )

    context = build_country_context("fr")

    assert context == {
        "public_holidays": [{"date": "2026-01-01", "name": "New Year's Day"}],
        "unesco_world_heritage_sites": [{"name": "Test Heritage"}],
    }
