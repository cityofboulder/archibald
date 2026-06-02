import pytest

from archibald.errors import handle_esri_errors, parse_esri_error
from archibald.exceptions import (
    AuthorizationError,
    NotFoundError,
    ServiceError,
    TokenExpiredError,
    TokenMissingError,
)
from tests.helpers import make_decorated_call, make_response


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
