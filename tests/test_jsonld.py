from datetime import datetime, timezone


def test_jsonld_deadline_parser_normalizes_date_only_to_utc():
    from app.connectors.jsonld import parse_application_deadline

    assert parse_application_deadline("2026-09-07") == datetime(2026, 9, 7, tzinfo=timezone.utc)


def test_jsonld_deadline_parser_normalizes_zulu_and_offset_values():
    from app.connectors.jsonld import parse_application_deadline

    assert parse_application_deadline("2026-09-07T12:30:00Z").tzinfo == timezone.utc
    assert parse_application_deadline("2026-09-07T22:30:00+10:00") == datetime(2026, 9, 7, 12, 30, tzinfo=timezone.utc)


def test_jsonld_deadline_parser_rejects_invalid_values():
    from app.connectors.jsonld import parse_application_deadline

    assert parse_application_deadline(None) is None
    assert parse_application_deadline("not-a-date") is None
