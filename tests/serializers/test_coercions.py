"""Tests for outbound coercion functions in _coercions.py."""

from __future__ import annotations

import warnings
from datetime import datetime

import pandas as pd
import pytest

from archibald.serializers._coercions import (
    _coerce_datetime,
    _coerce_float,
    _coerce_integer,
    _coerce_string,
    enforce_types,
    recode_domains,
)


class TestCoerceDatetime:
    def test_tz_aware_utc_returns_correct_ms(self):
        series = pd.Series([pd.Timestamp("1970-01-01 00:00:01", tz="UTC")], name="col")

        result = _coerce_datetime(series)

        assert result.iloc[0] == 1000

    def test_tz_aware_non_utc_returns_same_ms_as_utc_equivalent(self):
        # MST is UTC-7; midnight Mountain = 07:00 UTC
        utc_series = pd.Series(
            [pd.Timestamp("2024-01-15 07:00:00", tz="UTC")], name="col"
        )
        mountain_series = pd.Series(
            [pd.Timestamp("2024-01-15 00:00:00", tz="US/Mountain")], name="col"
        )

        assert (
            _coerce_datetime(utc_series).iloc[0]
            == _coerce_datetime(mountain_series).iloc[0]
        )

    def test_nat_becomes_none(self):
        series = pd.Series([pd.NaT], name="col", dtype="datetime64[ns, UTC]")

        result = _coerce_datetime(series)

        assert result.iloc[0] is None

    def test_tz_naive_warns(self):
        series = pd.Series([pd.Timestamp("2024-01-01")], name="EventDate")

        with pytest.warns(UserWarning, match="EventDate"):
            _coerce_datetime(series)

    def test_tz_naive_warning_includes_fix_hint(self):
        series = pd.Series([pd.Timestamp("2024-01-01")], name="EventDate")

        with pytest.warns(UserWarning, match="tz_localize"):
            _coerce_datetime(series)

    def test_tz_naive_still_produces_correct_ms(self):
        series = pd.Series([pd.Timestamp("1970-01-01 00:00:01")], name="col")

        with pytest.warns(UserWarning):
            result = _coerce_datetime(series)

        assert result.iloc[0] == 1000

    @pytest.mark.parametrize(
        "tz",
        ["UTC", "US/Mountain", "Europe/London"],
        ids=["utc", "mountain", "london"],
    )
    def test_tz_aware_does_not_warn(self, tz):
        series = pd.Series([pd.to_datetime("2024-01-01").tz_localize(tz)], name="col")

        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            _coerce_datetime(series)

    def test_result_is_all_none_when_object_series_is_all_null(self):
        series = pd.Series([None, None], name="col")

        result = _coerce_datetime(series)

        assert result.tolist() == [None, None]

    def test_no_warning_emitted_when_object_series_is_all_null(self):
        series = pd.Series([None, None], name="col")

        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            _coerce_datetime(series)

    @pytest.mark.parametrize(
        "value",
        [
            pd.Timestamp("1970-01-01 00:00:01", tz="UTC"),
            "1970-01-01T00:00:01+00:00",
        ],
        ids=["timestamp-utc", "iso-string-utc"],
    )
    def test_converts_to_ms_without_warning_when_object_series_is_tz_aware(self, value):
        series = pd.Series([value], name="col", dtype=object)

        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            result = _coerce_datetime(series)

        assert result.iloc[0] == 1000

    def test_converts_to_ms_when_object_series_contains_naive_datetime_objects(self):
        series = pd.Series([datetime(1970, 1, 1, 0, 0, 1)], name="col", dtype=object)

        with pytest.warns(UserWarning, match="col"):
            result = _coerce_datetime(series)

        assert result.iloc[0] == 1000

    def test_warns_tz_naive_when_object_series_contains_naive_strings(self):
        series = pd.Series(["1970-01-01T00:00:01"], name="EventDate", dtype=object)

        with pytest.warns(UserWarning, match="EventDate"):
            _coerce_datetime(series)

    def test_returns_none_and_warns_when_object_series_values_are_unparseable(self):
        series = pd.Series(["not-a-date"], name="col", dtype=object)

        with pytest.warns(UserWarning) as record:
            result = _coerce_datetime(series)

        assert result.iloc[0] is None
        assert len(record) == 1
        assert "1 value" in str(record[0].message)

    def test_warns_parse_failure_and_tz_naive_when_object_series_is_partially_unparseable(
        self,
    ):
        series = pd.Series(["2024-01-01", "bad"], name="col", dtype=object)

        with pytest.warns(UserWarning) as record:
            _coerce_datetime(series)

        messages = [str(w.message) for w in record]
        assert any("1 value" in m for m in messages)
        assert any("timezone-naive" in m for m in messages)

    def test_preserves_valid_values_as_ms_when_object_series_is_partially_unparseable(
        self,
    ):
        series = pd.Series(
            ["1970-01-01T00:00:01+00:00", "bad"], name="col", dtype=object
        )

        with pytest.warns(UserWarning):
            result = _coerce_datetime(series)

        assert result.iloc[0] == 1000
        assert result.iloc[1] is None

    def test_no_parse_failure_warning_when_object_series_has_null_and_valid_values(
        self,
    ):
        series = pd.Series(
            [None, pd.Timestamp("2024-01-01", tz="UTC")], name="col", dtype=object
        )

        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            _coerce_datetime(series)


class TestCoerceInteger:
    @pytest.mark.parametrize(
        "dtype",
        ["Int16", "Int32", "Int64"],
        ids=["int16", "int32", "int64"],
    )
    def test_integer_values_become_python_int(self, dtype):
        series = pd.Series([1, 2, 3], name="col")

        result = _coerce_integer(series, dtype)

        assert all(isinstance(v, int) for v in result)
        assert result.tolist() == [1, 2, 3]

    @pytest.mark.parametrize(
        "null_value",
        [None, float("nan"), pd.NA],
        ids=["none", "float-nan", "pd-na"],
    )
    def test_null_values_become_none(self, null_value):
        series = pd.Series([null_value], name="col")

        result = _coerce_integer(series, "Int32")

        assert result.iloc[0] is None

    def test_all_null_series_produces_no_warning(self):
        series = pd.Series([None, None], name="col")

        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            _coerce_integer(series, "Int32")

    def test_non_numeric_string_becomes_none_and_warns(self):
        series = pd.Series(["abc"], name="col")

        with pytest.warns(UserWarning, match="1 value"):
            result = _coerce_integer(series, "Int32")

        assert result.iloc[0] is None

    def test_failure_warning_includes_example_values(self):
        series = pd.Series(["abc", "xyz"], name="col")

        with pytest.warns(UserWarning, match="abc"):
            _coerce_integer(series, "Int32")

    def test_fractional_float_warns_precision_loss(self):
        series = pd.Series([1.7], name="col")

        with pytest.warns(UserWarning, match="fractional"):
            _coerce_integer(series, "Int32")

    def test_fractional_float_value_is_truncated_not_rounded(self):
        series = pd.Series([1.7], name="col")

        with pytest.warns(UserWarning):
            result = _coerce_integer(series, "Int32")

        assert result.iloc[0] == 1

    def test_whole_float_does_not_warn(self):
        series = pd.Series([2.0, 3.0], name="col")

        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            _coerce_integer(series, "Int32")

    def test_mixed_valid_and_invalid_emits_both_warnings(self):
        series = pd.Series(["abc", 1.7], name="col")

        with pytest.warns(UserWarning) as record:
            _coerce_integer(series, "Int32")

        assert len(record) == 2


class TestCoerceFloat:
    def test_float_values_become_python_float(self):
        series = pd.Series([1.5, 2.5], name="col")

        result = _coerce_float(series)

        assert all(isinstance(v, float) for v in result)
        assert result.tolist() == [1.5, 2.5]

    def test_nan_becomes_none(self):
        series = pd.Series([float("nan")], name="col")

        result = _coerce_float(series)

        assert result.iloc[0] is None

    @pytest.mark.parametrize(
        "null_value",
        [None, pd.NA],
        ids=["none", "pd-na"],
    )
    def test_null_values_become_none(self, null_value):
        series = pd.Series([null_value], name="col", dtype=object)

        result = _coerce_float(series)

        assert result.iloc[0] is None

    def test_all_null_series_produces_no_warning(self):
        series = pd.Series([None, None], name="col")

        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            _coerce_float(series)

    def test_non_numeric_string_becomes_none_and_warns(self):
        series = pd.Series(["abc"], name="col")

        with pytest.warns(UserWarning, match="1 value"):
            result = _coerce_float(series)

        assert result.iloc[0] is None

    def test_failure_warning_includes_example_values(self):
        series = pd.Series(["abc", "xyz"], name="col")

        with pytest.warns(UserWarning, match="abc"):
            _coerce_float(series)

    def test_integer_values_become_float_without_warning(self):
        series = pd.Series([1, 2, 3], name="col")

        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            result = _coerce_float(series)

        assert all(isinstance(v, float) for v in result)


class TestCoerceString:
    def test_string_values_returned_as_str(self):
        series = pd.Series(["hello", "world"], name="col")

        result = _coerce_string(series)

        assert result.tolist() == ["hello", "world"]

    def test_none_becomes_none_not_string(self):
        series = pd.Series([None], name="col", dtype=object)

        result = _coerce_string(series)

        assert result.iloc[0] is None

    def test_pd_na_becomes_none_not_string(self):
        series = pd.Series([pd.NA], name="col", dtype=object)

        result = _coerce_string(series)

        assert result.iloc[0] is None

    def test_float_nan_becomes_none_not_string(self):
        series = pd.Series([float("nan")], name="col")

        result = _coerce_string(series)

        assert result.iloc[0] is None

    def test_no_max_length_does_not_truncate(self):
        long_val = "x" * 1000
        series = pd.Series([long_val], name="col")

        result = _coerce_string(series)

        assert result.iloc[0] == long_val

    def test_values_within_max_length_not_truncated(self):
        series = pd.Series(["hello", "hi"], name="col")

        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            result = _coerce_string(series, max_length=10)

        assert result.tolist() == ["hello", "hi"]

    def test_values_over_max_length_are_truncated(self):
        series = pd.Series(["hello world"], name="col")

        with pytest.warns(UserWarning):
            result = _coerce_string(series, max_length=5)

        assert result.iloc[0] == "hello"

    def test_truncation_emits_warning_with_count(self):
        series = pd.Series(["too long", "also too long"], name="col")

        with pytest.warns(UserWarning, match="2 value"):
            _coerce_string(series, max_length=3)

    def test_null_values_not_counted_in_truncation(self):
        series = pd.Series([None, "hello"], name="col", dtype=object)

        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            result = _coerce_string(series, max_length=10)

        assert result.iloc[0] is None
        assert result.iloc[1] == "hello"

    def test_integer_column_converted_to_string(self):
        series = pd.Series([1, 2, 3], name="col")

        result = _coerce_string(series)

        assert result.tolist() == ["1", "2", "3"]


class TestEnforceTypes:
    def test_from_esri_converts_integer_to_nullable_dtype(self, fields_result):
        df = pd.DataFrame({"OBJECTID": [1, 2, 3]})

        result = enforce_types(df, fields_result, direction="from_esri")

        assert result["OBJECTID"].dtype == pd.Int64Dtype()

    def test_from_esri_converts_date_to_utc_datetime(self, fields_result):
        ms = 1_704_067_200_000  # 2024-01-01 00:00:00 UTC
        df = pd.DataFrame({"EventDate": [ms]})

        result = enforce_types(df, fields_result, direction="from_esri")

        assert str(result["EventDate"].dtype) == "datetime64[ms, UTC]"
        assert result["EventDate"].iloc[0] == pd.Timestamp("2024-01-01", tz="UTC")

    def test_to_esri_converts_datetime_to_ms_int(self, fields_result):
        df = pd.DataFrame(
            {"EventDate": pd.to_datetime(["2024-01-01"]).tz_localize("UTC")}
        )

        result = enforce_types(df, fields_result, direction="to_esri")

        assert result["EventDate"].iloc[0] == 1_704_067_200_000

    def test_to_esri_truncates_string_to_field_length(self, fields_result):
        # fields_result.Name has length=10; use an 11-char string to trigger truncation
        df = pd.DataFrame({"Name": ["way_too_long"]})

        with pytest.warns(UserWarning, match="truncated"):
            result = enforce_types(df, fields_result, direction="to_esri")

        assert result["Name"].iloc[0] == "way_too_lo"

    def test_leaves_unregistered_type_column_unchanged(self, fields_result):
        df = pd.DataFrame({"Unknown": [1, 2, 3]})

        result = enforce_types(df, fields_result, direction="from_esri")

        assert result["Unknown"].tolist() == [1, 2, 3]

    @pytest.mark.parametrize(
        "direction", ["from_esri", "to_esri"], ids=["from_esri", "to_esri"]
    )
    def test_returns_copy_not_inplace(self, fields_result, direction):
        df = pd.DataFrame({"OBJECTID": [1]})

        result = enforce_types(df, fields_result, direction=direction)

        assert result is not df

    @pytest.mark.parametrize(
        "direction", ["from_esri", "to_esri"], ids=["from_esri", "to_esri"]
    )
    def test_empty_dataframe_returns_empty(self, fields_result, direction):
        df = pd.DataFrame({"OBJECTID": pd.Series([], dtype="int64")})

        result = enforce_types(df, fields_result, direction=direction)

        assert result.empty


class TestRecodeDomains:
    @pytest.mark.parametrize(
        "direction, input_val, expected_val",
        [
            ("from_esri", 1, "Active"),
            ("from_esri", 0, "Inactive"),
            ("from_esri", 2, "Pending"),
            ("to_esri", "Active", 1),
            ("to_esri", "Inactive", 0),
            ("to_esri", "Pending", 2),
        ],
        ids=[
            "from-esri-code-1",
            "from-esri-code-0",
            "from-esri-code-2",
            "to-esri-active",
            "to-esri-inactive",
            "to-esri-pending",
        ],
    )
    def test_translates_domain_values(
        self, fields_result_with_domains, direction, input_val, expected_val
    ):
        df = pd.DataFrame({"Status": [input_val]})

        result = recode_domains(df, fields_result_with_domains, direction=direction)

        assert result["Status"].iloc[0] == expected_val

    @pytest.mark.parametrize(
        "direction, value",
        [("from_esri", 99), ("to_esri", "Unknown")],
        ids=["code-from-esri", "name-to-esri"],
    )
    def test_unmapped_value_passes_through_unchanged(
        self, fields_result_with_domains, direction, value
    ):
        df = pd.DataFrame({"Status": [value]})

        result = recode_domains(df, fields_result_with_domains, direction=direction)

        assert result["Status"].iloc[0] == value

    @pytest.mark.parametrize(
        "direction",
        ["from_esri", "to_esri"],
        ids=["from-esri", "to-esri"],
    )
    def test_null_value_preserved(self, fields_result_with_domains, direction):
        df = pd.DataFrame({"Status": [None]}, dtype=object)

        result = recode_domains(df, fields_result_with_domains, direction=direction)

        assert result["Status"].iloc[0] is None

    def test_non_domain_column_left_unchanged(self, fields_result_with_domains):
        df = pd.DataFrame({"Status": [1], "Name": ["Alice"]})

        result = recode_domains(df, fields_result_with_domains, direction="from_esri")

        assert result["Name"].iloc[0] == "Alice"

    def test_returns_original_df_when_no_domain_fields(self, fields_result):
        df = pd.DataFrame({"Status": [1]})

        result = recode_domains(df, fields_result, direction="from_esri")

        assert result is df

    def test_leaves_df_unchanged_when_domain_field_not_queried(
        self, fields_result_with_domains
    ):
        # Status has a domain but isn't in the DataFrame (e.g. out_fields omitted it).
        df = pd.DataFrame({"Name": ["Alice"]})

        result = recode_domains(df, fields_result_with_domains, direction="from_esri")

        assert list(result.columns) == ["Name"]

    def test_returns_copy_not_inplace(self, fields_result_with_domains):
        df = pd.DataFrame({"Status": [1]})

        result = recode_domains(df, fields_result_with_domains, direction="from_esri")

        assert result is not df

    @pytest.mark.parametrize(
        "direction, values",
        [
            ("from_esri", [1, 99]),
            ("to_esri", ["Active", "Unknown"]),
        ],
        ids=["from-esri-mixed", "to-esri-mixed"],
    )
    def test_warns_when_unmapped_values_mix_with_mapped(
        self, fields_result_with_domains, direction, values
    ):
        df = pd.DataFrame({"Status": values})

        with pytest.warns(UserWarning, match="Status"):
            recode_domains(df, fields_result_with_domains, direction=direction)

    def test_warning_includes_unmapped_example_values(self, fields_result_with_domains):
        df = pd.DataFrame({"Status": [1, 99, 100]})

        with pytest.warns(UserWarning, match="99"):
            recode_domains(df, fields_result_with_domains, direction="from_esri")

    def test_no_warning_when_all_values_mapped(self, fields_result_with_domains):
        df = pd.DataFrame({"Status": [0, 1, 2]})

        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            recode_domains(df, fields_result_with_domains, direction="from_esri")

    def test_no_warning_when_all_values_unmapped(self, fields_result_with_domains):
        # All unmapped → uniform passthrough, no mixed types, no warning.
        df = pd.DataFrame({"Status": [99, 100]})

        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            recode_domains(df, fields_result_with_domains, direction="from_esri")
