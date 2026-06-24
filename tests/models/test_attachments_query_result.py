"""Tests for AttachmentsQueryResult."""

import pytest

from archibald.models import AttachmentsQueryResult
from tests.helpers import make_attachment_info


class TestToFrameFullDefault:
    def test_columns_are_enabled_property_names(
        self, attachment_properties, full_attachment_groups, enabled_property_columns
    ):
        result = AttachmentsQueryResult(full_attachment_groups, attachment_properties)

        df = result.to_frame()

        assert list(df.columns) == enabled_property_columns

    def test_keeps_property_values_as_column_names_and_drops_esri_fields(
        self, attachment_properties, full_attachment_groups
    ):
        result = AttachmentsQueryResult(full_attachment_groups, attachment_properties)

        df = result.to_frame()

        assert df["id"].tolist() == [10, 11, 12]
        assert "ATTACHMENTID" not in df.columns

    def test_drops_disabled_properties_columns(
        self, attachment_properties, full_attachment_groups
    ):
        result = AttachmentsQueryResult(full_attachment_groups, attachment_properties)

        df = result.to_frame()

        assert "keywords" not in df.columns
        assert "exifInfo" not in df.columns

    def test_propagates_parent_ids_onto_every_row(
        self, attachment_properties, full_attachment_groups
    ):
        result = AttachmentsQueryResult(full_attachment_groups, attachment_properties)

        df = result.to_frame()

        assert df["parentObjectId"].tolist() == [1, 1, 2]
        assert df["parentGlobalId"].tolist() == ["g1", "g1", "g2"]


class TestToFrameFullFieldNames:
    def test_columns_are_enabled_field_names(
        self, attachment_properties, full_attachment_groups, enabled_field_name_columns
    ):
        result = AttachmentsQueryResult(full_attachment_groups, attachment_properties)

        df = result.to_frame(use_field_names=True)

        assert list(df.columns) == enabled_field_name_columns

    def test_values_carry_over_under_field_names(
        self, attachment_properties, full_attachment_groups
    ):
        result = AttachmentsQueryResult(full_attachment_groups, attachment_properties)

        df = result.to_frame(use_field_names=True)

        assert df["ATTACHMENTID"].tolist() == [10, 11, 12]
        assert "id" not in df.columns


class TestToFrameUrl:
    @pytest.mark.parametrize(
        "use_field_names", [False, True], ids=["property_names", "field_names"]
    )
    def test_url_included_regardless_of_naming(
        self, attachment_properties, use_field_names
    ):
        url = "https://example.com/rest/.../attachments/10"
        groups = [
            {
                "parentObjectId": 1,
                "parentGlobalId": "g1",
                "attachmentInfos": [make_attachment_info(10, url=url)],
            }
        ]
        result = AttachmentsQueryResult(groups, attachment_properties)

        df = result.to_frame(use_field_names=use_field_names)

        assert "url" in df.columns
        assert df["url"].tolist() == [url]


class TestToFrameConsistency:
    @pytest.mark.parametrize(
        "use_field_names", [False, True], ids=["property_names", "field_names"]
    )
    def test_empty_and_nonempty_share_columns(
        self,
        attachment_properties,
        full_attachment_groups,
        enabled_property_columns,
        enabled_field_name_columns,
        use_field_names,
    ):
        expected = (
            enabled_field_name_columns if use_field_names else enabled_property_columns
        )

        empty = AttachmentsQueryResult([], attachment_properties).to_frame(
            use_field_names=use_field_names
        )
        full = AttachmentsQueryResult(
            full_attachment_groups, attachment_properties
        ).to_frame(use_field_names=use_field_names)

        assert list(empty.columns) == expected
        assert list(full.columns) == expected
        assert empty.empty


class TestToFrameCountOnly:
    def test_returns_one_row_per_group(self, attachment_properties):
        groups = [
            {"parentObjectId": 1, "parentGlobalId": "g1", "count": 3},
            {"parentObjectId": 2, "parentGlobalId": "g2", "count": 0},
        ]
        result = AttachmentsQueryResult(
            groups, attachment_properties, return_count_only=True
        )

        df = result.to_frame()

        assert list(df.columns) == ["parentObjectId", "parentGlobalId", "count"]
        assert df["count"].tolist() == [3, 0]

    def test_empty_has_count_columns(self, attachment_properties):
        result = AttachmentsQueryResult(
            [], attachment_properties, return_count_only=True
        )

        df = result.to_frame()

        assert list(df.columns) == ["parentObjectId", "parentGlobalId", "count"]
        assert df.empty


class TestToFrameWarnsWithoutCrosswalk:
    def test_use_field_names_without_properties_warns_and_falls_back(
        self, full_attachment_groups
    ):
        result = AttachmentsQueryResult(full_attachment_groups, [])

        with pytest.warns(UserWarning, match="attachmentProperties"):
            df = result.to_frame(use_field_names=True)

        # No crosswalk: raw response columns are returned, no rename performed.
        assert df["id"].tolist() == [10, 11, 12]
        assert "ATTACHMENTID" in df.columns


class TestCoerceFields:
    @pytest.mark.parametrize(
        "use_field_names", [False, True], ids=["property_names", "field_names"]
    )
    def test_count_only_maps_parent_ids_and_count(
        self, attachment_properties, use_field_names
    ):
        result = AttachmentsQueryResult(
            [], attachment_properties, return_count_only=True
        )

        field_map = result._coerce_fields(use_field_names=use_field_names)

        assert field_map == {
            "parentObjectId": "parentObjectId",
            "parentGlobalId": "parentGlobalId",
            "count": "count",
        }

    def test_default_maps_property_names_to_themselves(self, attachment_properties):
        result = AttachmentsQueryResult([], attachment_properties)

        field_map = result._coerce_fields(use_field_names=False)

        assert field_map == {
            "parentObjectId": "parentObjectId",
            "parentGlobalId": "parentGlobalId",
            "id": "id",
            "globalId": "globalId",
            "name": "name",
            "size": "size",
            "contentType": "contentType",
        }

    def test_field_names_map_properties_to_esri_names(self, attachment_properties):
        result = AttachmentsQueryResult([], attachment_properties)

        field_map = result._coerce_fields(use_field_names=True)

        assert field_map == {
            "parentObjectId": "parentObjectId",
            "parentGlobalId": "parentGlobalId",
            "id": "ATTACHMENTID",
            "globalId": "GLOBALID",
            "name": "ATT_NAME",
            "size": "DATA_SIZE",
            "contentType": "CONTENT_TYPE",
        }

    def test_no_properties_returns_empty_map_without_warning(self, recwarn):
        result = AttachmentsQueryResult([], [])

        field_map = result._coerce_fields(use_field_names=False)

        assert field_map == {}
        assert len(recwarn) == 0

    def test_no_properties_with_field_names_warns(self):
        result = AttachmentsQueryResult([], [])

        with pytest.warns(UserWarning, match="attachmentProperties"):
            field_map = result._coerce_fields(use_field_names=True)

        assert field_map == {}


class TestBuildDataframe:
    def test_empty_map_returns_raw_normalized_frame(self):
        groups = [
            {
                "parentObjectId": 1,
                "parentGlobalId": "g1",
                "attachmentInfos": [make_attachment_info(10)],
            }
        ]
        result = AttachmentsQueryResult(groups, [])

        df = result._build_dataframe({})

        assert df["id"].tolist() == [10]
        assert "ATTACHMENTID" in df.columns

    def test_empty_map_no_groups_returns_parent_columns(self):
        result = AttachmentsQueryResult([], [])

        df = result._build_dataframe({})

        assert list(df.columns) == ["parentObjectId", "parentGlobalId"]
        assert df.empty

    def test_no_groups_returns_output_columns(self):
        result = AttachmentsQueryResult([], [])
        field_map = {"parentObjectId": "parentObjectId", "name": "ATT_NAME"}

        df = result._build_dataframe(field_map)

        assert list(df.columns) == ["parentObjectId", "ATT_NAME"]
        assert df.empty

    def test_projects_and_renames_and_appends_url(self):
        url = "https://example.com/attachments/10"
        groups = [
            {
                "parentObjectId": 1,
                "parentGlobalId": "g1",
                "attachmentInfos": [make_attachment_info(10, url=url)],
            }
        ]
        result = AttachmentsQueryResult(groups, [])
        field_map = {
            "parentObjectId": "parentObjectId",
            "parentGlobalId": "parentGlobalId",
            "name": "ATT_NAME",
        }

        df = result._build_dataframe(field_map)

        assert list(df.columns) == [
            "parentObjectId",
            "parentGlobalId",
            "ATT_NAME",
            "url",
        ]
        assert df["ATT_NAME"].tolist() == ["photo.jpg"]
        assert df["url"].tolist() == [url]
        assert "name" not in df.columns
