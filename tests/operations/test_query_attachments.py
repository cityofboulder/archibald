"""Tests for QueryAttachmentsOperation."""

import pytest

from archibald.exceptions import InvalidParameterError
from archibald.models import AttachmentsQueryResult
from tests.helpers import (
    make_attachment_info,
    make_esri_query_attachments_response,
    make_response,
)


def _set_keywords_enabled(layer, *, enabled: bool) -> None:
    layer.attachment_properties.return_value = [
        {"name": "keywords", "fieldName": "KEYWORDS", "isEnabled": enabled}
    ]


def _set_exif_enabled(layer, *, enabled: bool) -> None:
    layer.attachment_properties.return_value = [
        {"name": "exifInfo", "fieldName": "EXIFINFO", "isEnabled": enabled}
    ]


def _set_order_by_supported(layer, *, enabled: bool) -> None:
    layer.supports_query_attachments_order_by_fields.return_value = enabled


# Capability-gated params: (request kwargs, error match, gate configurator).
_CAPABILITY_GATED = [
    ({"keywords": "site"}, "keywords", _set_keywords_enabled),
    ({"return_metadata": True}, "return_metadata", _set_exif_enabled),
    ({"order_by_fields": "size DESC"}, "order_by_fields", _set_order_by_supported),
]
_CAPABILITY_GATED_IDS = ["keywords", "return_metadata", "order_by_fields"]


class TestExecuteRequest:
    @pytest.mark.anyio
    async def test_gets_correct_endpoint(self, query_attachments_op):
        query_attachments_op._layer._client.get.return_value = make_response(
            make_esri_query_attachments_response([])
        )

        await query_attachments_op.execute(object_ids=[1])
        call = query_attachments_op._layer._client.get.call_args

        assert (
            call.kwargs["endpoint"]
            == "services/MyService/FeatureServer/0/queryAttachments"
        )

    @pytest.mark.anyio
    async def test_returns_attachments_query_result_with_groups(
        self, query_attachments_op
    ):
        groups = [
            {
                "parentObjectId": 1,
                "parentGlobalId": "g1",
                "attachmentInfos": [make_attachment_info(10)],
            }
        ]
        query_attachments_op._layer._client.get.return_value = make_response(
            make_esri_query_attachments_response(groups)
        )

        result = await query_attachments_op.execute(object_ids=[1])

        assert isinstance(result, AttachmentsQueryResult)
        assert result.attachment_groups == groups
        assert result.return_count_only is False

    @pytest.mark.anyio
    async def test_defaults_groups_to_empty_when_key_absent(self, query_attachments_op):
        query_attachments_op._layer._client.get.return_value = make_response({})

        result = await query_attachments_op.execute(object_ids=[1])

        assert result.attachment_groups == []


class TestValidateParams:
    # _validate_params is async and reads keyword/order-by support from the layer.
    pytestmark = pytest.mark.anyio

    @pytest.mark.parametrize(
        "selector",
        [
            {"object_ids": [1]},
            {"global_ids": ["g1"]},
            {"definition_expression": "1=1"},
            {"object_ids": [1], "definition_expression": "STATE='CO'"},
        ],
        ids=[
            "object_ids_only",
            "global_ids_only",
            "definition_expression_only",
            "object_ids_with_definition_expression",
        ],
    )
    async def test_accepts_valid_selectors(self, query_attachments_op, selector):
        defaults = {
            "object_ids": None,
            "global_ids": None,
            "definition_expression": None,
            "size": None,
        }

        await query_attachments_op._validate_params(**{**defaults, **selector})

    async def test_raises_when_no_feature_selector(self, query_attachments_op):
        with pytest.raises(InvalidParameterError, match="at least one"):
            await query_attachments_op._validate_params(
                object_ids=None,
                global_ids=None,
                definition_expression=None,
                size=None,
            )

    async def test_raises_when_object_ids_and_global_ids_both_supplied(
        self, query_attachments_op
    ):
        with pytest.raises(InvalidParameterError, match="mutually exclusive"):
            await query_attachments_op._validate_params(
                object_ids=[1],
                global_ids=["g1"],
                definition_expression=None,
                size=None,
            )

    @pytest.mark.parametrize(
        "size",
        [(1000,), [1000], (1000, 2000), [1000, 2000], "1000", "1000,", "1000,2000"],
        ids=[
            "min_only_tuple",
            "min_only_list",
            "range_tuple",
            "range_list",
            "min_only_str",
            "min_trailing_comma_str",
            "range_str",
        ],
    )
    async def test_accepts_valid_size(self, query_attachments_op, size):
        await query_attachments_op._validate_params(
            object_ids=[1],
            global_ids=None,
            definition_expression=None,
            size=size,
        )

    @pytest.mark.parametrize(
        "size,match",
        [
            ((1000, 2000, 3000), "pair"),
            ([1000, 2000, 3000], "pair"),
            ("1000,2000,3000", "pair"),
            ((), "pair"),
            ((1000, None), "None"),
            ((None, 1000), "None"),
            (",1000", "max-only"),
        ],
        ids=[
            "three_tuple",
            "three_list",
            "three_str",
            "empty_tuple",
            "none_max_tuple",
            "none_min_tuple",
            "missing_min_str",
        ],
    )
    async def test_raises_when_size_invalid(self, query_attachments_op, size, match):
        with pytest.raises(InvalidParameterError, match=match):
            await query_attachments_op._validate_params(
                object_ids=[1],
                global_ids=None,
                definition_expression=None,
                size=size,
            )

    async def test_execute_raises_before_request(self, query_attachments_op):
        with pytest.raises(InvalidParameterError, match="at least one"):
            await query_attachments_op.execute()

        query_attachments_op._layer._client.get.assert_not_called()

    @pytest.mark.parametrize(
        "kwargs,match,configure", _CAPABILITY_GATED, ids=_CAPABILITY_GATED_IDS
    )
    async def test_raises_when_capability_disabled(
        self, query_attachments_op, kwargs, match, configure
    ):
        configure(query_attachments_op._layer, enabled=False)

        with pytest.raises(InvalidParameterError, match=match):
            await query_attachments_op._validate_params(
                object_ids=[1],
                global_ids=None,
                definition_expression=None,
                size=None,
                **kwargs,
            )

    @pytest.mark.parametrize(
        "kwargs,configure",
        [(kwargs, configure) for kwargs, _match, configure in _CAPABILITY_GATED],
        ids=_CAPABILITY_GATED_IDS,
    )
    async def test_accepts_when_capability_enabled(
        self, query_attachments_op, kwargs, configure
    ):
        configure(query_attachments_op._layer, enabled=True)

        await query_attachments_op._validate_params(
            object_ids=[1],
            global_ids=None,
            definition_expression=None,
            size=None,
            **kwargs,
        )

    @pytest.mark.parametrize(
        "kwargs,match,configure", _CAPABILITY_GATED, ids=_CAPABILITY_GATED_IDS
    )
    async def test_execute_raises_when_capability_disabled(
        self, query_attachments_op, kwargs, match, configure
    ):
        configure(query_attachments_op._layer, enabled=False)

        with pytest.raises(InvalidParameterError, match=match):
            await query_attachments_op.execute(object_ids=[1], **kwargs)

        query_attachments_op._layer._client.get.assert_not_called()


class TestBuildParams:
    @pytest.mark.parametrize(
        "kwargs,expected",
        [
            ({"object_ids": [1, 2, 3]}, {"objectIds": "1,2,3"}),
            ({"global_ids": ["a", "b"]}, {"globalIds": "a,b"}),
            ({"object_ids": "1,2"}, {"objectIds": "1,2"}),
            (
                {"definition_expression": "STATE='CO'"},
                {"definitionExpression": "STATE='CO'"},
            ),
            (
                {"attachments_definition_expression": "CONTENT_TYPE='image/jpeg'"},
                {"attachmentsDefinitionExpression": "CONTENT_TYPE='image/jpeg'"},
            ),
            ({"attachment_types": ["jpeg", "pdf"]}, {"attachmentTypes": "jpeg,pdf"}),
            ({"size": (1000, 15000)}, {"size": "1000,15000"}),
            ({"keywords": "site"}, {"keywords": "site"}),
            ({"keywords": ["site", "plan"]}, {"keywords": "site,plan"}),
            ({"order_by_fields": "size DESC"}, {"orderByFields": "size DESC"}),
            ({"result_offset": 10}, {"resultOffset": 10}),
            ({"result_record_count": 50}, {"resultRecordCount": 50}),
            ({"return_url": True}, {"returnUrl": "true"}),
            ({"return_metadata": False}, {"returnMetadata": "false"}),
        ],
        ids=[
            "object_ids_list_joined",
            "global_ids_list_joined",
            "object_ids_string_passthrough",
            "definition_expression",
            "attachments_definition_expression",
            "attachment_types_joined",
            "size_tuple_joined",
            "keywords",
            "keywords_list_joined",
            "order_by_fields",
            "result_offset",
            "result_record_count",
            "return_url_bool_stringified",
            "return_metadata_bool_stringified",
        ],
    )
    def test_maps_named_args_to_camelcase(self, query_attachments_op, kwargs, expected):
        full_kwargs = {
            "object_ids": None,
            "global_ids": None,
            "definition_expression": None,
            "attachments_definition_expression": None,
            "attachment_types": None,
            "size": None,
            "keywords": None,
            "return_url": None,
            "return_metadata": None,
            "order_by_fields": None,
            "result_offset": None,
            "result_record_count": None,
            "return_count_only": False,
            **kwargs,
        }

        params = query_attachments_op._build_params(**full_kwargs)

        for key, value in expected.items():
            assert params[key] == value

    def test_omits_none_valued_params(self, query_attachments_op):
        params = query_attachments_op._build_params(
            object_ids=[1],
            global_ids=None,
            definition_expression=None,
            attachments_definition_expression=None,
            attachment_types=None,
            size=None,
            keywords=None,
            return_url=None,
            return_metadata=None,
            order_by_fields=None,
            result_offset=None,
            result_record_count=None,
            return_count_only=False,
        )

        assert "globalIds" not in params
        assert "keywords" not in params
        assert "returnUrl" not in params

    def test_return_count_only_always_present(self, query_attachments_op):
        params = query_attachments_op._build_params(
            object_ids=[1],
            global_ids=None,
            definition_expression=None,
            attachments_definition_expression=None,
            attachment_types=None,
            size=None,
            keywords=None,
            return_url=None,
            return_metadata=None,
            order_by_fields=None,
            result_offset=None,
            result_record_count=None,
            return_count_only=True,
        )

        assert params["returnCountOnly"] == "true"

    def test_passes_through_extra_kwargs(self, query_attachments_op):
        params = query_attachments_op._build_params(
            object_ids=None,
            global_ids=None,
            definition_expression=None,
            attachments_definition_expression=None,
            attachment_types=None,
            size=None,
            keywords=None,
            return_url=None,
            return_metadata=None,
            order_by_fields=None,
            result_offset=None,
            result_record_count=None,
            return_count_only=False,
            cacheHint="true",
        )

        assert params["cacheHint"] == "true"


class TestExecuteAttachmentProperties:
    @pytest.mark.anyio
    async def test_passes_layer_attachment_properties_to_result(
        self, query_attachments_op, attachment_properties
    ):
        query_attachments_op._layer._client.get.return_value = make_response(
            make_esri_query_attachments_response([])
        )

        result = await query_attachments_op.execute(object_ids=[1])

        query_attachments_op._layer.attachment_properties.assert_awaited()
        assert result.attachment_properties == attachment_properties
