import uuid
from datetime import date, datetime, timezone

from app.db.repository import _json_mapping


def test_json_mapping_serializes_database_dates_and_identifiers():
    value = _json_mapping(
        {
            "id": uuid.UUID("191e459d-831a-4bed-a624-5144a98d16df"),
            "campaign_start_date": date(2026, 8, 1),
            "completed_at": datetime(2026, 9, 28, tzinfo=timezone.utc),
        }
    )

    assert value == {
        "id": "191e459d-831a-4bed-a624-5144a98d16df",
        "campaign_start_date": "2026-08-01",
        "completed_at": "2026-09-28T00:00:00+00:00",
    }
