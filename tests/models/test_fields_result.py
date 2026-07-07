"""Tests for FieldsResult dataclass."""

import pytest
import pandas as pd

from archibald.exceptions import InvalidParameterError
from archibald.models import FieldsResult


class TestNames:
    def test_names_returns_all_field_names(self, fields_result):
        assert fields_result.names == [
            "OBJECTID",
            "Name",
            "Status",
            "Score",
            "EventDate",
        ]

    def test_names_returns_empty_list_when_no_fields(self):
        assert FieldsResult(fields=[]).names == []


class TestTypes:
    def test_returns_name_to_type_mapping(self, fields_result):
        result = fields_result.field_type_map

        assert result == {
            "OBJECTID": "esriFieldTypeOID",
            "Name": "esriFieldTypeString",
            "Status": "esriFieldTypeInteger",
            "Score": "esriFieldTypeDouble",
            "EventDate": "esriFieldTypeDate",
        }

    def test_returns_empty_dict_when_no_fields(self):
        result = FieldsResult(fields=[]).field_type_map

        assert result == {}


class TestToFrame:
    def test_returns_dataframe_with_one_row_per_field(self, fields_result):
        result = fields_result.to_frame()

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 5
        assert result["name"].tolist() == [
            "OBJECTID",
            "Name",
            "Status",
            "Score",
            "EventDate",
        ]

    def test_returns_empty_dataframe_when_no_fields(self):
        result = FieldsResult(fields=[]).to_frame()

        assert isinstance(result, pd.DataFrame)
        assert result.empty


class TestDomainMaps:
    def test_returns_empty_dict_when_no_fields_have_domains(self, fields_result):
        result = fields_result.domain_maps

        assert result == {}

    def test_returns_to_name_and_to_code_maps_for_coded_value_field(
        self, fields_result_with_domains
    ):
        result = fields_result_with_domains.domain_maps

        assert result["Status"]["to_name"] == {0: "Inactive", 1: "Active", 2: "Pending"}
        assert result["Status"]["to_code"] == {"Active": 1, "Inactive": 0, "Pending": 2}

    def test_non_domain_fields_excluded_from_result(self, fields_result_with_domains):
        result = fields_result_with_domains.domain_maps

        assert "OBJECTID" not in result
        assert "Name" not in result

    def test_non_coded_value_domain_type_excluded(self):
        fr = FieldsResult(
            fields=[
                {
                    "name": "Score",
                    "type": "esriFieldTypeDouble",
                    "domain": {
                        "type": "range",
                        "name": "ScoreRange",
                        "range": [0, 100],
                    },
                }
            ]
        )

        assert fr.domain_maps == {}

    def test_returns_empty_dict_when_no_fields(self):
        assert FieldsResult(fields=[]).domain_maps == {}


class TestFilter:
    @pytest.mark.parametrize(
        "names, expected",
        [
            (["OBJECTID"], ["OBJECTID"]),
            (["OBJECTID", "Name"], ["OBJECTID", "Name"]),
            (["Unknown"], []),
            ([], []),
        ],
        ids=["single", "multiple", "unknown", "empty-list"],
    )
    def test_filter_by_names_returns_matching_fields(
        self, fields_result, names, expected
    ):
        result = fields_result.filter(names=names)

        assert result.names == expected

    @pytest.mark.parametrize(
        "types, expected",
        [
            ("esriFieldTypeOID", ["OBJECTID"]),
            (["esriFieldTypeOID", "esriFieldTypeInteger"], ["OBJECTID", "Status"]),
            ("esriFieldTypeBlob", []),
        ],
        ids=["single-string", "list-of-types", "unmatched-type"],
    )
    def test_filter_by_types_returns_matching_fields(
        self, fields_result, types, expected
    ):
        result = fields_result.filter(types=types)

        assert result.names == expected

    @pytest.mark.parametrize(
        "editable, expected",
        [
            (True, ["Name", "Status", "Score", "EventDate"]),
            (False, ["OBJECTID"]),
        ],
        ids=["editable-only", "non-editable-only"],
    )
    def test_filter_by_editable_returns_matching_fields(
        self, fields_result, editable, expected
    ):
        result = fields_result.filter(editable=editable)

        assert result.names == expected

    @pytest.mark.parametrize(
        "nullable, expected",
        [
            (
                True,
                ["Name", "Status", "Score", "EventDate"],
            ),  # explicit True + absent key (defaults True)
            (False, ["OBJECTID"]),
        ],
        ids=["nullable-only", "non-nullable-only"],
    )
    def test_filter_by_nullable_returns_matching_fields(
        self, fields_result, nullable, expected
    ):
        result = fields_result.filter(nullable=nullable)

        assert result.names == expected

    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            ({"names": ["OBJECTID", "Name"], "editable": True}, ["Name"]),
            ({"types": "esriFieldTypeInteger", "editable": True}, ["Status"]),
            (
                {"editable": True, "nullable": True},
                ["Name", "Status", "Score", "EventDate"],
            ),
        ],
        ids=["names-and-editable", "types-and-editable", "editable-and-nullable"],
    )
    def test_filter_combines_criteria(self, fields_result, kwargs, expected):
        result = fields_result.filter(**kwargs)

        assert result.names == expected

    def test_filter_with_no_args_returns_all_fields(self, fields_result):
        result = fields_result.filter()

        assert result.names == fields_result.names

    def test_filter_returns_new_instance(self, fields_result):
        assert fields_result.filter() is not fields_result

    def test_filter_raises_when_names_and_types_both_given(self, fields_result):
        with pytest.raises(
            InvalidParameterError, match="names and types cannot be specified together"
        ):
            fields_result.filter(names=["OBJECTID"], types="esriFieldTypeOID")

    @pytest.mark.parametrize(
        "types",
        [
            "InvalidType",
            ["esriFieldTypeOID", "NotAnEsriType"],
        ],
        ids=["single-invalid", "mixed-valid-and-invalid"],
    )
    def test_filter_raises_when_types_are_not_valid_esri_field_types(
        self, fields_result, types
    ):
        with pytest.raises(InvalidParameterError, match="Invalid ESRI type"):
            fields_result.filter(types=types)

    @pytest.mark.parametrize(
        "esri_type",
        [
            "esriFieldTypeDateOnly",
            "esriFieldTypeTimeOnly",
            "esriFieldTypeTimestampOffset",
        ],
        ids=["date-only", "time-only", "timestamp-offset"],
    )
    def test_filter_accepts_newer_esri_date_types_without_raising(
        self, fields_result, esri_type
    ):
        result = fields_result.filter(types=esri_type)

        assert result.names == []
