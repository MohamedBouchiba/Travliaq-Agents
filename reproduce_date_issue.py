
import sys
import os
from datetime import date, datetime

# Add the project root to the python path
sys.path.append(os.path.abspath("e:/CrewTravliaq/Travliaq-Agents"))

from app.crew_pipeline.trip_structural_enricher import enrich_trip_structural_data

def test_dates():
    print(f"Current date: {date.today()}")

    # Test Case 1: Past absolute dates
    print("\n--- Test Case 1: Past absolute dates (2023) ---")
    questionnaire_past = {
        "date_depart": "2023-12-01",
        "date_retour": "2023-12-15",
        "nuits_exactes": 14
    }
    result_past = enrich_trip_structural_data({}, questionnaire_past)
    print(f"Input: {questionnaire_past}")
    print(f"Output Dates: {result_past.get('trip_frame', {}).get('dates')}")

    # Test Case 2: Relative dates (if supported?)
    print("\n--- Test Case 2: Relative dates (next month) ---")
    questionnaire_relative = {
        "date_depart_approximative": "next month", # This likely won't work as per code review
        "duree": 7
    }
    result_relative = enrich_trip_structural_data({}, questionnaire_relative)
    print(f"Input: {questionnaire_relative}")
    print(f"Output Dates: {result_relative.get('trip_frame', {}).get('dates')}")

    # Test Case 3: No dates
    print("\n--- Test Case 3: No dates ---")
    questionnaire_none = {
        "destination": "Paris"
    }
    result_none = enrich_trip_structural_data({}, questionnaire_none)
    print(f"Input: {questionnaire_none}")
    print(f"Output Dates: {result_none.get('trip_frame', {}).get('dates')}")

    # Test Case 4: Flexible dates with approx date in past
    print("\n--- Test Case 4: Flexible dates with approx date in past ---")
    questionnaire_flex_past = {
        "date_depart_approximative": "2023-12-01",
        "flexibilite": 3,
        "duree": 7
    }
    result_flex_past = enrich_trip_structural_data({}, questionnaire_flex_past)
    print(f"Input: {questionnaire_flex_past}")
    print(f"Output Dates: {result_flex_past.get('trip_frame', {}).get('dates')}")

if __name__ == "__main__":
    test_dates()
