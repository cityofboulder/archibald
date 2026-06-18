import pytest

from archibald.models.edit_result_item import EditResultItem


class TestEditResultItem:
    def test_parses_success_item(self):
        item = {"objectId": 1, "globalId": "{ABC-123}", "success": True, "error": None}

        result = EditResultItem._from_esri(item)

        assert result.object_id == 1
        assert result.global_id == "{ABC-123}"
        assert result.success is True
        assert result.error is None

    def test_parses_failure_item(self):
        error = {"code": 1001, "description": "Insert failed."}
        item = {"objectId": 2, "globalId": None, "success": False, "error": error}

        result = EditResultItem._from_esri(item)

        assert result.success is False
        assert result.error == error

    def test_object_id_defaults_to_minus_one_when_absent(self):
        result = EditResultItem._from_esri({"success": True})

        assert result.object_id == -1

    def test_global_id_is_none_when_absent(self):
        result = EditResultItem._from_esri({"objectId": 1, "success": True})

        assert result.global_id is None

    def test_success_defaults_to_false_when_absent(self):
        result = EditResultItem._from_esri({"objectId": 1})

        assert result.success is False

    def test_error_is_none_when_absent(self):
        result = EditResultItem._from_esri({"objectId": 1, "success": True})

        assert result.error is None

    def test_success_coerced_to_bool(self):
        result = EditResultItem._from_esri({"objectId": 1, "success": 1})

        assert result.success is True
        assert type(result.success) is bool

    @pytest.mark.parametrize(
        "attr, esri_key, value",
        [
            ("object_id", "objectId", 42),
            ("global_id", "globalId", "{GUID-XYZ}"),
            ("success", "success", True),
            ("error", "error", {"code": 500, "description": "Server error"}),
        ],
        ids=["objectId", "globalId", "success", "error"],
    )
    def test_field_mapping(self, attr, esri_key, value):
        item = {"objectId": 0, "success": True, esri_key: value}

        result = EditResultItem._from_esri(item)

        assert getattr(result, attr) == value
