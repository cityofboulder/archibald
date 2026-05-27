"""Tests for QueryOperation."""

import pytest

from archie.models.query_result import QueryResult
from tests.helpers import make_feature, make_response


class TestNormalizeOutFields:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "out_fields,expected",
        [
            (None, "OBJECTID,Name,Status"),
            ("*", "OBJECTID,Name,Status"),
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
        with pytest.raises(ValueError, match=match):
            await query_op._validate_fields(out_fields)


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


class TestFetchRemainingPages:
    @pytest.mark.anyio
    async def test_returns_empty_when_count_equals_max_record_count(
        self, query_op, mock_layer
    ):
        mock_layer._client.get.return_value = make_response({"count": 1000})

        result = await query_op._fetch_remaining_pages({"where": "1=1"}, {})

        assert result == []

    @pytest.mark.anyio
    async def test_fetches_single_additional_page(self, query_op, mock_layer):
        page_features = [make_feature(1001), make_feature(1002)]

        def get_side_effect(endpoint, *, params=None, **kwargs):
            if params and params.get("returnCountOnly") == "true":
                return make_response({"count": 1500})
            return make_response({"features": page_features})

        mock_layer._client.get.side_effect = get_side_effect

        result = await query_op._fetch_remaining_pages({"where": "1=1"}, {})

        assert result == page_features

    @pytest.mark.anyio
    async def test_fetches_multiple_pages_in_order(self, query_op, mock_layer):
        page2_features = [make_feature(1001)]
        page3_features = [make_feature(2001)]

        def get_side_effect(endpoint, *, params=None, **kwargs):
            if params and params.get("returnCountOnly") == "true":
                return make_response({"count": 2500})
            offset = params.get("resultOffset")  # type: ignore
            if offset == 1000:
                return make_response({"features": page2_features})
            return make_response({"features": page3_features})

        mock_layer._client.get.side_effect = get_side_effect

        result = await query_op._fetch_remaining_pages({"where": "1=1"}, {})

        assert result == page2_features + page3_features


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
    async def test_no_pagination_when_transfer_limit_not_exceeded(
        self, query_op, mock_layer, mocker
    ):
        mock_layer._client.get.return_value = make_response(
            {"features": [make_feature(1)]}
        )
        mock_fetch = mocker.patch.object(query_op, "_fetch_remaining_pages")

        await query_op.execute(out_fields=["OBJECTID", "Name"])

        mock_fetch.assert_not_called()

