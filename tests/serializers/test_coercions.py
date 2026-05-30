"""Tests for outbound coercion functions in _coercions.py."""

from __future__ import annotations

import warnings

import pandas as pd
import pytest

from archie.serializers._coercions import (
    _coerce_datetime,
    _coerce_float,
    _coerce_integer,
    _coerce_string,
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

        assert _coerce_datetime(utc_series).iloc[0] == _coerce_datetime(mountain_series).iloc[0]

    def test_nat_becomes_none(self):
        series = pd.Series([pd.NaT], name="col", dtype="datetime64[ns, UTC]")

        result = _coerce_datetime(series)

        assert result.iloc[0] is None

    def test_tz_naive_warns(self):
        series = pd.Series([pd.Timestamp("2024-01-01")], name="col")

        with pytest.warns(UserWarning):
            _coerce_datetime(series)

    def test_tz_naive_still_produces_correct_ms(self):
        series = pd.Series([pd.Timestamp("1970-01-01 00:00:01")], name="col")

        with pytest.warns(UserWarning):
            result = _coerce_datetime(series)

        assert result.iloc[0] == 1000


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
