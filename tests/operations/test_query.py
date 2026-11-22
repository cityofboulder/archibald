"""Tests for QueryOperation."""

import pytest

from archibald.exceptions import InvalidParameterError
from archibald.models import FieldsResult, QueryResult
from tests.helpers import (
    make_feature,
    make_first_page,
    make_paging_side_effect,
    make_response,
)


class TestNormalizeOutFields:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "out_fields,expected",
        [
            (None, "OBJECTID,Name,Status,Score,EventDate"),
            ("*", "OBJECTID,Name,Status,Score,EventDate"),
            (["OBJECTID", "Name"], "OBJECTID,Name"),
            ([" OBJECTID ", " Name "], "OBJECTID,Name"),
            ("  OBJECTID,Name  ", "OBJECTID,Name"),
        ],
        ids=[
            "none_returns_all_fields",
            "wildcard_returns_all_fields",
            "list_returns_comma_joined",
            "list_strips_whitespace_per_item",
            "string_is_stripped",
        ],
    )
    async def test_normalizes_out_fields(self, query_op, out_fields, expected):
        result = await query_op._normalize_out_fields(out_fields)

        assert result == expected


class TestValidateFields:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "out_fields",
        ["OBJECTID", "OBJECTID,Name", "OBJECTID,Name,Status"],
        ids=["single_field", "partial_fields", "all_fields"],
    )
    async def test_valid_fields_returned_unchanged(self, query_op, out_fields):
        result = await query_op._validate_fields(out_fields)

        assert result == out_fields

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "out_fields,match",
        [
            ("OBJECTID,Ghost", "Ghost"),
            ("Foo,Bar", "Foo"),
            ("name", "name"),
        ],
        ids=[
            "single_unknown_field",
            "multiple_unknown_fields",
            "case_sensitive_mismatch",
        ],
    )
    async def test_raises_for_unknown_fields(self, query_op, out_fields, match):
        with pytest.raises(InvalidParameterError, match=match):
            await query_op._validate_fields(out_fields)


class TestValidateDateLiterals:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "where",
        [
            "Status = 1",
            "EventDate = DATE '2020-01-01'",
            "EventDate = TIMESTAMP '2020-01-01 10:00:00'",
            "EventDate BETWEEN DATE '2020-01-01' AND DATE '2020-01-05'",
            "EventDate NOT BETWEEN DATE '2020-01-01' AND DATE '2020-01-05'",
            "EventDate IN (DATE '2020-01-01', DATE '2020-01-02')",
            "EventDate NOT IN (DATE '2020-01-01')",
            "Name = '2020-01-01'",
        ],
        ids=[
            "no_date_field_referenced",
            "date_keyword",
            "timestamp_keyword",
            "between_valid",
            "not_between_valid",
            "in_list_valid",
            "not_in_list_valid",
            "string_field_resembling_date_ignored",
        ],
    )
    async def test_passes_for_valid_where_clauses(self, query_op, where):
        await query_op._validate_date_literals(where)

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "where, match",
        [
            ("EventDate = '2020-01-01'", "bare string literal"),
            ("EventDate = DATE '01/01/2020'", "malformed DATE literal"),
            ("EventDate = TIMESTAMP '2020-01-01'", "malformed TIMESTAMP literal"),
            (
                "EventDate BETWEEN DATE '2020/01/01' AND DATE '2020-01-05'",
                "malformed DATE literal",
            ),
            (
                "EventDate BETWEEN '2020-01-01' AND DATE '2020-01-05'",
                "bare string literal",
            ),
            (
                "EventDate NOT BETWEEN DATE '2020-01-01' AND DATE '2020/01/05'",
                "malformed DATE literal",
            ),
            (
                "EventDate IN (DATE '2020-01-01', DATE '2020/01/02')",
                "malformed DATE literal",
            ),
            (
                "EventDate IN (DATE '2020-01-01', '2020-01-02')",
                "bare string literal",
            ),
            (
                "EventDate NOT IN (DATE '2020/01/01')",
                "malformed DATE literal",
            ),
            ("EventDate = TIME '14:35:00'", "does not support the 'TIME' keyword"),
        ],
        ids=[
            "bare_literal",
            "malformed_date_format",
            "timestamp_missing_time",
            "between_first_literal_malformed",
            "between_first_literal_bare",
            "not_between_second_literal_malformed",
            "in_list_contains_malformed_literal",
            "in_list_contains_bare_literal",
            "not_in_list_contains_malformed_literal",
            "wrong_keyword_for_field_type",
        ],
    )
    async def test_raises_for_invalid_where_clauses(self, query_op, where, match):
        with pytest.raises(InvalidParameterError, match=match):
            await query_op._validate_date_literals(where)

    @pytest.mark.anyio
    async def test_raises_when_dateonly_field_given_timestamp_keyword(
        self, query_op, mock_layer
    ):
        mock_layer.fields.return_value = FieldsResult(
            fields=[{"name": "EventDateOnly", "type": "esriFieldTypeDateOnly"}]
        )

        with pytest.raises(
            InvalidParameterError, match="does not support the 'TIMESTAMP' keyword"
        ):
            await query_op._validate_date_literals(
                "EventDateOnly = TIMESTAMP '2020-01-01 10:00:00'"
            )

    @pytest.mark.anyio
    async def test_raises_when_timeonly_field_given_date_keyword(
        self, query_op, mock_layer
    ):
        mock_layer.fields.return_value = FieldsResult(
            fields=[{"name": "EventTimeOnly", "type": "esriFieldTypeTimeOnly"}]
        )

        with pytest.raises(
            InvalidParameterError, match="does not support the 'DATE' keyword"
        ):
            await query_op._validate_date_literals("EventTimeOnly = DATE '2020-01-01'")

    @pytest.mark.anyio
    async def test_raises_when_timestamp_offset_literal_missing_offset(
        self, query_op, mock_layer
    ):
        mock_layer.fields.return_value = FieldsResult(
            fields=[{"name": "EventTsOffset", "type": "esriFieldTypeTimestampOffset"}]
        )

        with pytest.raises(InvalidParameterError, match="malformed TIMESTAMP literal"):
            await query_op._validate_date_literals(
                "EventTsOffset = TIMESTAMP '2020-01-01 10:00:00'"
            )


class TestBuildParams:
    @pytest.mark.anyio
    async def test_core_keys_always_present(self, query_op):
        params = await query_op._build_params(
            where="Status = 1",
            out_fields="OBJECTID,Name",
            return_geometry=False,
        )

        assert params["where"] == "Status = 1"
        assert params["outFields"] == "OBJECTID,Name"
        assert params["returnGeometry"] == "false"

    @pytest.mark.anyio
    async def test_adds_geojson_format_when_return_geometry_true(self, query_op):
        params = await query_op._build_params(
            where="1=1", out_fields="OBJECTID", return_geometry=True
        )

        assert params["f"] == "geojson"

    @pytest.mark.anyio
    async def test_overrides_format_param_when_return_geometry_true(self, query_op):
        params = await query_op._build_params(
            where="1=1",
            out_fields="OBJECTID",
            return_geometry=True,
            f="json",
        )

        assert params["f"] == "geojson"

    @pytest.mark.anyio
    async def test_omits_format_param_when_return_geometry_false(self, query_op):
        params = await query_op._build_params(
            where="1=1", out_fields="OBJECTID", return_geometry=False
        )

        assert "f" not in params

    @pytest.mark.anyio
    async def test_out_sr_stringified_when_provided(self, query_op):
        params = await query_op._build_params(
            where="1=1", out_fields="OBJECTID", return_geometry=True, out_sr=4326
        )

        assert params["outSR"] == "4326"

    @pytest.mark.anyio
    async def test_out_sr_omitted_when_none(self, query_op):
        params = await query_op._build_params(
            where="1=1", out_fields="OBJECTID", return_geometry=True
        )

        assert "outSR" not in params

    @pytest.mark.anyio
    async def test_default_order_by_objectid_asc(self, query_op):
        params = await query_op._build_params(
            where="1=1", out_fields="OBJECTID", return_geometry=False
        )

        assert params["orderByFields"] == "OBJECTID ASC"

    @pytest.mark.anyio
    async def test_default_order_by_overridden_when_param_provided(self, query_op):
        params = await query_op._build_params(
            where="1=1",
            out_fields="OBJECTID",
            return_geometry=False,
            orderByFields="Name DESC",
        )

        assert params["orderByFields"] == "Name DESC"

    @pytest.mark.anyio
    async def test_extra_kwargs_merged_into_params(self, query_op):
        params = await query_op._build_params(
            where="1=1",
            out_fields="OBJECTID",
            return_geometry=False,
            resultType="tile",
        )

        assert params["resultType"] == "tile"

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "window,expected",
        [
            (
                {"resultOffset": "500", "resultRecordCount": "1"},
                {"resultOffset": 500, "resultRecordCount": 1},
            ),
            (
                {"resultOffset": 500, "resultRecordCount": 1},
                {"resultOffset": 500, "resultRecordCount": 1},
            ),
            ({}, {}),
        ],
        ids=["strings_cast_to_int", "ints_unchanged", "omitted_when_not_supplied"],
    )
    async def test_window_params_cast_to_int_when_supplied(
        self, query_op, window, expected
    ):
        params = await query_op._build_params(
            where="1=1",
            out_fields="OBJECTID",
            return_geometry=False,
            **window,
        )

        actual = {
            k: params[k] for k in ("resultOffset", "resultRecordCount") if k in params
        }
        assert actual == expected


class TestFetchRemainingPages:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "window,first_data",
        [
            ({}, make_first_page(0, 1000, exceeded=False)),
            ({}, make_first_page(0, 1000, exceeded=False, in_properties=True)),
            ({"resultRecordCount": 1}, make_first_page(0, 1)),
            ({"resultOffset": 500, "resultRecordCount": 1}, make_first_page(500, 1)),
        ],
        ids=[
            "flag_not_set",
            "flag_not_set_in_properties",
            "record_count_met_by_first_page",
            "offset_and_record_count_met_by_first_page",
        ],
    )
    async def test_makes_no_requests_when_nothing_remains(
        self, query_op, mock_layer, window, first_data
    ):
        params = {"where": "1=1", **window}

        result = await query_op._fetch_remaining_pages(params, first_data)

        assert result == []
        mock_layer._client.get.assert_not_called()

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "window,first_data,total,expected_oids",
        [
            ({}, make_first_page(0, 1000), 1000, []),
            ({}, make_first_page(0, 1000), 2500, range(1000, 2500)),
            ({}, make_first_page(0, 500), 1200, range(500, 1200)),
            ({}, make_first_page(0, 1000, in_properties=True), 1500, range(1000, 1500)),
            ({}, make_first_page(0, 0), 1500, range(0, 1500)),
            (
                {"resultOffset": 500},
                make_first_page(500, 1000),
                2500,
                range(1500, 2500),
            ),
            (
                {"resultRecordCount": 1500},
                make_first_page(0, 1000),
                2500,
                range(1000, 1500),
            ),
            (
                {"resultOffset": 2000, "resultRecordCount": 1000},
                make_first_page(2000, 400),
                2500,
                range(2400, 2500),
            ),
        ],
        ids=[
            "total_equals_first_page",
            "full_first_page",
            "short_first_page_sizes_later_pages",
            "flag_in_properties",
            "empty_first_page_falls_back_to_max_record_count",
            "offset_pages_to_end",
            "record_count_above_max_trims_last_page",
            "offset_and_record_count_capped_by_total",
        ],
    )
    async def test_fetches_exactly_the_rest_of_the_window(
        self, query_op, mock_layer, window, first_data, total, expected_oids
    ):
        mock_layer._client.get.side_effect = make_paging_side_effect(total)
        params = {"where": "1=1", **window}

        result = await query_op._fetch_remaining_pages(params, first_data)

        assert [f["properties"]["OBJECTID"] for f in result] == list(expected_oids)


class TestExecute:
    @pytest.mark.anyio
    async def test_returns_query_result_for_single_page(self, query_op, mock_layer):
        features = [make_feature(1), make_feature(2)]
        mock_layer._client.get.return_value = make_response({"features": features})

        result = await query_op.execute(where="1=1", out_fields=["OBJECTID", "Name"])

        assert isinstance(result, QueryResult)
        assert result.features == features

    @pytest.mark.anyio
    async def test_result_geojson_true_when_geometry_returned(
        self, query_op, mock_layer
    ):
        mock_layer._client.get.return_value = make_response({"features": []})

        result = await query_op.execute(return_geometry=True)

        assert result.geojson is True

    @pytest.mark.anyio
    async def test_result_geojson_false_and_crs_none_when_no_geometry(
        self, query_op, mock_layer
    ):
        mock_layer._client.get.return_value = make_response({"features": []})

        result = await query_op.execute(return_geometry=False)

        assert result.geojson is False
        assert result.crs is None

    @pytest.mark.anyio
    async def test_result_crs_equals_explicit_out_sr(self, query_op, mock_layer):
        mock_layer._client.get.return_value = make_response({"features": []})

        result = await query_op.execute(return_geometry=True, out_sr=4326)

        assert result.crs == 4326

    @pytest.mark.anyio
    async def test_result_crs_defaults_to_layer_crs_when_out_sr_omitted(
        self, query_op, mock_layer
    ):
        mock_layer._client.get.return_value = make_response({"features": []})

        result = await query_op.execute(return_geometry=True)

        assert result.crs == 3857

    @pytest.mark.anyio
    async def test_result_crs_none_when_no_geometry_even_if_out_sr_provided(
        self, query_op, mock_layer
    ):
        mock_layer._client.get.return_value = make_response({"features": []})

        result = await query_op.execute(return_geometry=False, out_sr=4326)

        assert result.crs is None

    @pytest.mark.anyio
    async def test_paginates_when_exceeded_transfer_limit(
        self, query_op, mock_layer, mocker
    ):
        first_page = [make_feature(1)]
        second_page = [make_feature(2)]
        mock_layer._client.get.return_value = make_response(
            {"features": first_page, "exceededTransferLimit": True}
        )
        mocker.patch.object(
            query_op, "_fetch_remaining_pages", return_value=second_page
        )

        result = await query_op.execute(out_fields=["OBJECTID", "Name"])

        assert result.features == first_page + second_page

    @pytest.mark.anyio
    async def test_raises_invalid_parameter_error_when_where_clause_has_bad_date_literal(
        self, query_op, mock_layer
    ):
        with pytest.raises(InvalidParameterError, match="bare string literal"):
            await query_op.execute(where="EventDate = '2020-01-01'")

        mock_layer._client.get.assert_not_called()
