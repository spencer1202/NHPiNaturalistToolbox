import pytest
from unittest.mock import MagicMock, patch
import requests

from inatdatapipeline.client.annotations import AnnotationOptions, fetch_annotations
from inatdatapipeline.client.authentication import INaturalistAuth


class TestAnnotationOptions:
    """Test cases for the AnnotationOptions dataclass."""

    def test_annotation_options_initialization(self):
        """Test that AnnotationOptions initializes with empty lists."""
        options = AnnotationOptions()
        assert options.categories == []
        assert options.values == []

    def test_annotation_options_with_data(self):
        """Test that AnnotationOptions can be initialized with data."""
        categories = [{"annotation_id": 1, "label": "Life Stage"}]
        values = [{"value_id": 1, "annotation_id": 1, "label": "Adult"}]
        
        options = AnnotationOptions(categories=categories, values=values)
        assert options.categories == categories
        assert options.values == values

    def test_annotation_options_append_category(self):
        """Test appending a category to AnnotationOptions."""
        options = AnnotationOptions()
        category = {"annotation_id": 1, "label": "Life Stage"}
        options.categories.append(category)
        
        assert len(options.categories) == 1
        assert options.categories[0] == category

    def test_annotation_options_append_value(self):
        """Test appending a value to AnnotationOptions."""
        options = AnnotationOptions()
        value = {"value_id": 1, "annotation_id": 1, "label": "Adult"}
        options.values.append(value)
        
        assert len(options.values) == 1
        assert options.values[0] == value


class TestFetchAnnotations:
    """Test cases for the fetch_annotations function."""

    def test_fetch_annotations_success(self, auth):
        """Test successful fetching of annotations."""
        mock_response = {
            "results": [
                {
                    "id": 1,
                    "label": "Life Stage",
                    "values": [
                        {"id": 10, "label": "Adult"},
                        {"id": 11, "label": "Juvenile"}
                    ]
                },
                {
                    "id": 2,
                    "label": "Sex",
                    "values": [
                        {"id": 20, "label": "Male"}
                    ]
                }
            ]
        }

        with patch("inatdatapipeline.client.annotations.requests.get") as mock_get:
            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.raise_for_status.return_value = None

            result = fetch_annotations(auth)

            assert isinstance(result, AnnotationOptions)
            assert len(result.categories) == 2
            assert len(result.values) == 3

    def test_fetch_annotations_categories_structure(self, auth):
        """Test that categories have the correct structure."""
        mock_response = {
            "results": [
                {
                    "id": 1,
                    "label": "Life Stage",
                    "values": [
                        {"id": 10, "label": "Adult"}
                    ]
                }
            ]
        }

        with patch("inatdatapipeline.client.annotations.requests.get") as mock_get:
            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.raise_for_status.return_value = None

            result = fetch_annotations(auth)

            assert result.categories[0]["annotation_id"] == 1
            assert result.categories[0]["label"] == "Life Stage"

    def test_fetch_annotations_values_structure(self, auth):
        """Test that values have the correct structure."""
        mock_response = {
            "results": [
                {
                    "id": 1,
                    "label": "Life Stage",
                    "values": [
                        {"id": 10, "label": "Adult"},
                        {"id": 11, "label": "Juvenile"}
                    ]
                }
            ]
        }

        with patch("inatdatapipeline.client.annotations.requests.get") as mock_get:
            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.raise_for_status.return_value = None

            result = fetch_annotations(auth)

            assert len(result.values) == 2
            assert result.values[0]["value_id"] == 10
            assert result.values[0]["annotation_id"] == 1
            assert result.values[0]["label"] == "Adult"
            assert result.values[1]["value_id"] == 11
            assert result.values[1]["annotation_id"] == 1
            assert result.values[1]["label"] == "Juvenile"

    def test_fetch_annotations_no_results(self, auth):
        """Test error handling when API response has no results."""
        mock_response = {"results": []}

        with patch("inatdatapipeline.client.annotations.requests.get") as mock_get:
            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.raise_for_status.return_value = None

            with pytest.raises(ValueError, match="Annotation API response did not contain results"):
                fetch_annotations(auth)

    def test_fetch_annotations_missing_results_key(self, auth):
        """Test error handling when results key is missing from response."""
        mock_response = {}

        with patch("inatdatapipeline.client.annotations.requests.get") as mock_get:
            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.raise_for_status.return_value = None

            with pytest.raises(ValueError, match="Annotation API response did not contain results"):
                fetch_annotations(auth)

    def test_fetch_annotations_no_values(self, auth):
        """Test error handling when an annotation has no values."""
        mock_response = {
            "results": [
                {
                    "id": 1,
                    "label": "Life Stage",
                    "values": []
                }
            ]
        }

        with patch("inatdatapipeline.client.annotations.requests.get") as mock_get:
            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.raise_for_status.return_value = None

            with pytest.raises(ValueError, match="Annotation has no values"):
                fetch_annotations(auth)

    def test_fetch_annotations_missing_values_key(self, auth):
        """Test error handling when values key is missing from annotation."""
        mock_response = {
            "results": [
                {
                    "id": 1,
                    "label": "Life Stage"
                }
            ]
        }

        with patch("inatdatapipeline.client.annotations.requests.get") as mock_get:
            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.raise_for_status.return_value = None

            with pytest.raises(ValueError, match="Annotation has no values"):
                fetch_annotations(auth)

    def test_fetch_annotations_request_exception(self, auth):
        """Test error handling for request exceptions."""
        with patch("inatdatapipeline.client.annotations.requests.get") as mock_get:
            mock_get.side_effect = requests.exceptions.RequestException("Connection error")

            with pytest.raises(ValueError, match="Request to fetch annotation options failed."):
                fetch_annotations(auth)

    def test_fetch_annotations_timeout(self, auth):
        """Test error handling for request timeouts."""
        with patch("inatdatapipeline.client.annotations.requests.get") as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout("Request timed out")

            with pytest.raises(ValueError, match="Request to fetch annotation options failed."):
                fetch_annotations(auth)

    def test_fetch_annotations_http_error(self, auth):
        """Test error handling for HTTP errors."""
        with patch("inatdatapipeline.client.annotations.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Not Found")

            with pytest.raises(ValueError, match="Request to fetch annotation options failed."):
                fetch_annotations(auth)

    def test_fetch_annotations_multiple_annotations(self, auth):
        """Test fetching multiple annotations with multiple values each."""
        mock_response = {
            "results": [
                {
                    "id": 1,
                    "label": "Life Stage",
                    "values": [
                        {"id": 10, "label": "Adult"},
                        {"id": 11, "label": "Juvenile"},
                        {"id": 12, "label": "Egg"}
                    ]
                },
                {
                    "id": 2,
                    "label": "Sex",
                    "values": [
                        {"id": 20, "label": "Male"},
                        {"id": 21, "label": "Female"}
                    ]
                },
                {
                    "id": 3,
                    "label": "Behavior",
                    "values": [
                        {"id": 30, "label": "Foraging"}
                    ]
                }
            ]
        }

        with patch("inatdatapipeline.client.annotations.requests.get") as mock_get:
            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.raise_for_status.return_value = None

            result = fetch_annotations(auth)

            assert len(result.categories) == 3
            assert len(result.values) == 6
            # Verify values are grouped by annotation
            assert all(v["annotation_id"] == 1 for v in result.values[:3])
            assert all(v["annotation_id"] == 2 for v in result.values[3:5])
            assert all(v["annotation_id"] == 3 for v in result.values[5:])

    def test_fetch_annotations_null_fields(self, auth):
        """Test handling of null/missing fields in API response."""
        mock_response = {
            "results": [
                {
                    "id": 1,
                    "label": None,
                    "values": [
                        {"id": 10, "label": "Adult"}
                    ]
                }
            ]
        }

        with patch("inatdatapipeline.client.annotations.requests.get") as mock_get:
            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.raise_for_status.return_value = None

            result = fetch_annotations(auth)

            assert result.categories[0]["label"] is None
            assert result.values[0]["label"] == "Adult"
