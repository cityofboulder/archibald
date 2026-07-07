"""Tests for the ESRI_DATE_TYPE_KEYWORDS table and matches_literal_format in _date_literals.py."""

from __future__ import annotations

import pytest

from archibald.serializers._date_literals import (
    ESRI_DATE_TYPE_KEYWORDS,
    matches_literal_format,
)


class TestAllowedKeywordsPerType:
    @pytest.mark.parametrize(
        "esri_type, expected_keywords",
        [
            ("esriFieldTypeDate", {"DATE", "TIMESTAMP"}),
            ("esriFieldTypeDateOnly", {"DATE"}),
            ("esriFieldTypeTimeOnly", {"TIME"}),
            ("esriFieldTypeTimestampOffset", {"TIMESTAMP"}),
        ],
        ids=["date", "date-only", "time-only", "timestamp-offset"],
    )
    def test_type_allows_expected_keywords(self, esri_type, expected_keywords):
        assert set(ESRI_DATE_TYPE_KEYWORDS[esri_type]) == expected_keywords


class TestMatchesLiteralFormat:
    @pytest.mark.parametrize(
        "esri_type, keyword, value",
        [
            ("esriFieldTypeDate", "DATE", "2018-06-05"),
            ("esriFieldTypeDate", "TIMESTAMP", "2018-06-05 14:35:00"),
            ("esriFieldTypeDateOnly", "DATE", "2018-06-05"),
            ("esriFieldTypeTimeOnly", "TIME", "14:35:00"),
            ("esriFieldTypeTimestampOffset", "TIMESTAMP", "2018-06-05 14:35:00 -08:00"),
            ("esriFieldTypeTimestampOffset", "TIMESTAMP", "2018-06-05 14:35:00 +05:30"),
        ],
        ids=[
            "date-value",
            "timestamp-value",
            "date-only-value",
            "time-only-value",
            "timestamp-offset-negative",
            "timestamp-offset-positive",
        ],
    )
    def test_accepts_valid_value(self, esri_type, keyword, value):
        assert matches_literal_format(value, esri_type, keyword)

    @pytest.mark.parametrize(
        "esri_type, keyword, value",
        [
            ("esriFieldTypeDate", "DATE", "06/05/2018"),
            ("esriFieldTypeDate", "TIMESTAMP", "2018-06-05"),
            ("esriFieldTypeDateOnly", "DATE", "2018-6-5"),
            ("esriFieldTypeTimeOnly", "TIME", "2:35 PM"),
            ("esriFieldTypeTimestampOffset", "TIMESTAMP", "2018-06-05 14:35:00"),
        ],
        ids=[
            "date-wrong-format",
            "timestamp-missing-time",
            "date-only-unpadded",
            "time-only-not-24h",
            "timestamp-offset-missing-offset",
        ],
    )
    def test_rejects_wrong_shape(self, esri_type, keyword, value):
        assert not matches_literal_format(value, esri_type, keyword)

    @pytest.mark.parametrize(
        "esri_type, keyword, value",
        [
            ("esriFieldTypeDate", "DATE", "2020-13-01"),
            ("esriFieldTypeDate", "DATE", "2020-01-32"),
            ("esriFieldTypeTimeOnly", "TIME", "25:00:00"),
            ("esriFieldTypeTimeOnly", "TIME", "10:61:00"),
        ],
        ids=[
            "month-out-of-range",
            "day-out-of-range",
            "hour-out-of-range",
            "minute-out-of-range",
        ],
    )
    def test_rejects_correctly_shaped_but_invalid_calendar_value(
        self, esri_type, keyword, value
    ):
        assert not matches_literal_format(value, esri_type, keyword)
