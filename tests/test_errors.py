import httpx
import pytest

from archibald.errors import (
    failed_items,
    handle_esri_errors,
    is_outcome_unknown,
    parse_esri_error,
)
from archibald.exceptions import (
    AuthorizationError,
    NotFoundError,
    ServiceError,
    TokenExpiredError,
    TokenMissingError,
)
from tests.helpers import (
    NON_ENVELOPE_FAILURE_CASES,
    OUTCOME_UNKNOWN_CASES,
    make_arcgis_error,
    make_decorated_call,
    make_response,
)


class TestIsOutcomeUnknown:
    @pytest.mark.parametrize("exc, expected", OUTCOME_UNKNOWN_CASES)
    def test_returns_expected_when_exception_given(self, exc, expected):
        assert is_outcome_unknown(exc) is expected


class TestFailedItems:
    def test_returns_one_failed_item_per_id_in_order_when_ids_given(self):
        exc = httpx.ReadTimeout("slow")

        items = failed_items(exc, [3, 1, 2], outcome_unknown=True)

        assert [item.object_id for item in items] == [3, 1, 2]
        assert all(item.success is False for item in items)

    @pytest.mark.parametrize("outcome_unknown", [True, False], ids=["unknown", "known"])
    def test_returns_server_error_when_exception_carries_envelope(
        self, outcome_unknown
    ):
        exc = make_arcgis_error(ServiceError, 400, "Unable to complete operation.")

        items = failed_items(exc, [1, 2], outcome_unknown=outcome_unknown)

        assert [item.error for item in items] == [
            {"code": 400, "message": "Unable to complete operation."}
        ] * 2

    @pytest.mark.parametrize("outcome_unknown", [True, False], ids=["unknown", "known"])
    @pytest.mark.parametrize("exc", NON_ENVELOPE_FAILURE_CASES)
    def test_returns_exception_error_when_exception_has_no_envelope(
        self, exc, outcome_unknown
    ):
        items = failed_items(exc, [7], outcome_unknown=outcome_unknown)

        assert items[0].error is not None
        assert items[0].error["exception"] == type(exc).__name__
        assert items[0].error["outcome_unknown"] is outcome_unknown


class TestParseEsriError:
    def test_returns_none_when_no_error_key(self):
        response = make_response({"results": []})

        result = parse_esri_error(response)

        assert result is None

    @pytest.mark.parametrize(
        "code,exc_class",
        [
            (498, TokenExpiredError),
            (499, TokenMissingError),
            (403, AuthorizationError),
            (404, NotFoundError),
            (500, ServiceError),
            (999, ServiceError),
        ],
    )
    def test_maps_code_to_correct_exception_class(self, code, exc_class):
        body = {"error": {"code": code, "message": "test error", "details": []}}
        response = make_response(body)

        result = parse_esri_error(response)

        assert isinstance(result, exc_class)

    def test_parsed_attributes_populated(self):
        body = {
            "error": {"code": 403, "message": "Access denied", "details": ["detail1"]}
        }
        response = make_response(body)

        result = parse_esri_error(response)

        assert result is not None
        assert result.code == 403
        assert result.message == "Access denied"
        assert result.details == ["detail1"]

    def test_raw_response_is_full_body(self):
        body = {"error": {"code": 403, "message": "Access denied", "details": []}}
        response = make_response(body)

        result = parse_esri_error(response)

        assert result is not None
        assert result.raw_response == body

    def test_missing_code_defaults_to_service_error(self):
        body = {"error": {"message": "Something broke"}}
        response = make_response(body)

        result = parse_esri_error(response)

        assert isinstance(result, ServiceError)
        assert result.code == -1

    def test_missing_message_defaults_to_unknown(self):
        body = {"error": {"code": 500}}
        response = make_response(body)

        result = parse_esri_error(response)

        assert result is not None
        assert result.message == "Unknown error"

    def test_missing_details_defaults_to_empty_list(self):
        body = {"error": {"code": 500, "message": "Error"}}
        response = make_response(body)

        result = parse_esri_error(response)

        assert result is not None
        assert result.details == []


class TestHandleEsriErrors:
    @pytest.mark.anyio
    async def test_returns_response_when_no_error(self):
        call = make_decorated_call({"results": []})

        result = await call()

        assert result.json() == {"results": []}

    @pytest.mark.anyio
    async def test_raises_on_esri_error_envelope(self):
        call = make_decorated_call(
            {"error": {"code": 498, "message": "Invalid token.", "details": []}}
        )

        with pytest.raises(TokenExpiredError):
            await call()

    @pytest.mark.anyio
    async def test_preserves_wrapped_function_name(self):
        @handle_esri_errors
        async def my_specific_function():
            return make_response({})

        assert my_specific_function.__name__ == "my_specific_function"

    @pytest.mark.anyio
    async def test_passes_args_and_kwargs_through(self):
        received = {}

        @handle_esri_errors
        async def mock_call(a, *, b):
            received["a"] = a
            received["b"] = b
            return make_response({})

        await mock_call(1, b=2)

        assert received == {"a": 1, "b": 2}
