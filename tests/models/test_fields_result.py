"""Tests for FieldsResult dataclass."""

import pytest
import pandas as pd

from archie.models.fields_result import FieldsResult


class TestNames:
    @pytest.mark.parametrize(
        "editable_only, expected",
        [
            (False, ["OBJECTID", "Name", "Status"]),
            (True, ["Name", "Status"]),
        ],
        ids=["all", "editable-only"],
    )
    def test_returns_correct_names(self, fields_result, editable_only, expected):
        result = fields_result.names(editable_only=editable_only)

        assert result == expected

    def test_returns_empty_list_when_no_fields(self):
        qr = FieldsResult(fields=[])

        assert qr.names() == []
        assert qr.names(editable_only=True) == []


class TestTypes:
    def test_returns_name_to_type_mapping(self, fields_result):
        result = fields_result.esri_field_types()

        assert result == {
            "OBJECTID": "esriFieldTypeOID",
            "Name": "esriFieldTypeString",
            "Status": "esriFieldTypeInteger",
        }

    def test_returns_empty_dict_when_no_fields(self):
        result = FieldsResult(fields=[]).esri_field_types()

        assert result == {}


class TestToFrame:
    def test_returns_dataframe_with_one_row_per_field(self, fields_result):
        result = fields_result.to_frame()

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3
        assert result["name"].tolist() == ["OBJECTID", "Name", "Status"]

    def test_returns_empty_dataframe_when_no_fields(self):
        result = FieldsResult(fields=[]).to_frame()

        assert isinstance(result, pd.DataFrame)
        assert result.empty
