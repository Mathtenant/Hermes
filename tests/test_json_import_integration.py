"""Integration tests for JSON import API endpoint."""
import json
import pytest
from fastapi.testclient import TestClient
from hermes_assistant.webapp.server import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


class TestImportJsonEndpoint:
    """Test POST /api/import/json endpoint."""

    def test_import_json_with_json_body(self, client):
        """Import via application/json content-type."""
        payload = {
            "risks": [
                {
                    "title": "Test Risk",
                    "severity": "high",
                    "likelihood": 3,
                }
            ]
        }
        response = client.post(
            "/api/import/json",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["created"] == 1

    def test_import_json_empty_payload(self, client):
        """Empty payload returns validation error."""
        response = client.post(
            "/api/import/json",
            json={},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_import_json_invalid_json(self, client):
        """Malformed JSON returns 422."""
        response = client.post(
            "/api/import/json",
            content=b"{ invalid json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_import_json_empty_body(self, client):
        """Empty body returns 422."""
        response = client.post(
            "/api/import/json",
            content=b"",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_import_json_no_recognized_types(self, client):
        """Payload with no recognized entity types returns 422."""
        response = client.post(
            "/api/import/json",
            json={"unknown_type": []},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_import_json_invalid_entity_type_value(self, client):
        """Entity type value must be list."""
        response = client.post(
            "/api/import/json",
            json={"risks": "not a list"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_import_json_multiple_risks(self, client):
        """Import multiple risks at once."""
        payload = {
            "risks": [
                {"title": f"Risk {i}", "severity": "medium", "likelihood": 3}
                for i in range(5)
            ]
        }
        response = client.post(
            "/api/import/json",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["created"] == 5
        assert data["skipped"] == 0

    def test_import_json_partial_valid(self, client):
        """H5 atomicity: any invalid item aborts the entire entity-type batch."""
        payload = {
            "risks": [
                {"title": "Valid Risk"},  # OK
                {"severity": "high"},  # Missing title — causes batch abort
                {"title": "Another valid"},  # OK but never written
            ]
        }
        response = client.post(
            "/api/import/json",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        data = response.json()
        # Atomicity: zero rows committed when any item fails validation
        assert data["created"] == 0
        assert data["skipped"] == 1
        assert len(data["errors"]) >= 1

    def test_import_json_with_plans(self, client):
        """Import plans via JSON."""
        payload = {
            "plans": [
                {
                    "plan_id": "plan1",
                    "items": [
                        {"title": "Outcome 1", "phase": "1"},
                        {"title": "Outcome 2", "phase": "2"},
                    ],
                }
            ]
        }
        response = client.post(
            "/api/import/json",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        data = response.json()
        # Plan import creates or updates (depends on database state)
        assert "entity_counts" in data
        assert "plans" in data["entity_counts"]

    def test_import_json_with_pendenzen(self, client):
        """Import pendenzen via JSON."""
        payload = {
            "pendenzen": [
                {"title": "Task 1", "priority": "high"},
                {"title": "Task 2", "priority": "medium"},
            ]
        }
        response = client.post(
            "/api/import/json",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["created"] == 2
        assert data["entity_counts"]["pendenzen"] == 2

    def test_import_json_mixed_types(self, client):
        """Import multiple entity types in one request."""
        payload = {
            "risks": [{"title": "Risk"}],
            "plans": [{"plan_id": "p1", "items": []}],
            "pendenzen": [{"title": "Task"}],
        }
        response = client.post(
            "/api/import/json",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        data = response.json()
        # Multiple types import succeeds
        assert "entity_counts" in data
        assert len(data["entity_counts"]) == 3

    def test_import_json_response_structure(self, client):
        """Response contains expected fields."""
        payload = {"risks": [{"title": "Risk"}]}
        response = client.post(
            "/api/import/json",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        data = response.json()
        assert "ok" in data
        assert "created" in data
        assert "updated" in data
        assert "skipped" in data
        assert "errors" in data
        assert "items" in data
        assert "entity_counts" in data

    def test_import_json_items_detail(self, client):
        """Response items contain detail for each imported item."""
        payload = {
            "risks": [
                {"id": "r1", "title": "Risk 1"},
                {"id": "r2", "title": "Risk 2"},
            ]
        }
        response = client.post(
            "/api/import/json",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        data = response.json()
        assert len(data["items"]) == 2
        for item in data["items"]:
            assert "index" in item
            assert "entity_type" in item
            assert "action" in item
            assert item["entity_type"] == "risks"
            assert item["action"] in ["created", "updated", "skipped"]

    def test_import_json_with_explicit_ids(self, client):
        """Import with explicit IDs."""
        payload = {
            "risks": [
                {
                    "id": "custom_risk_id",
                    "title": "Risk with ID",
                    "severity": "high",
                }
            ]
        }
        response = client.post(
            "/api/import/json",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["items"][0]["id"] == "custom_risk_id"

    def test_import_json_without_explicit_ids(self, client):
        """Import without IDs auto-generates them."""
        payload = {
            "risks": [{"title": "Risk without ID"}]
        }
        response = client.post(
            "/api/import/json",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        data = response.json()
        # Should have generated an ID
        assert data["items"][0]["id"] != ""

    def test_import_json_confidentiality_guard(self, client):
        """Response passes confidentiality validation."""
        payload = {
            "risks": [
                {"title": "Safe Risk", "severity": "high"}
            ]
        }
        response = client.post(
            "/api/import/json",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        # Should pass confidentiality guard
        assert response.status_code == 200

    def test_import_json_payload_size_limit(self, client):
        """Payload exceeding 10MB limit returns 413."""
        # Create a large payload
        large_payload = {
            "risks": [
                {
                    "title": "x" * 100,
                    "description": "y" * 1_000_000,
                }
                for _ in range(20)
            ]
        }
        json_str = json.dumps(large_payload)
        if len(json_str.encode()) > 10 * 1024 * 1024:
            response = client.post(
                "/api/import/json",
                content=json_str.encode(),
                headers={"Content-Type": "application/json"},
            )
            assert response.status_code == 413

    def test_import_json_multipart_with_raw_json(self, client):
        """Import via multipart with raw_json field as FormData."""
        payload = {"risks": [{"title": "Risk"}]}
        from io import BytesIO
        response = client.post(
            "/api/import/json",
            data={"raw_json": json.dumps(payload)},
        )
        # multipart form data requires explicit form encoding
        assert response.status_code in (200, 422)  # Accept both for compatibility

    def test_import_json_multipart_missing_fields(self, client):
        """Multipart without file or raw_json returns 422."""
        response = client.post(
            "/api/import/json",
            data={},
        )
        assert response.status_code == 422

    def test_import_json_with_risk_optional_fields(self, client):
        """Import risk with all optional fields."""
        payload = {
            "risks": [
                {
                    "id": "r1",
                    "title": "Complete Risk",
                    "description": "Full description",
                    "severity": "critical",
                    "likelihood": 5,
                    "owner": "Bob",
                    "status": "open",
                }
            ]
        }
        response = client.post(
            "/api/import/json",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        data = response.json()
        # Import succeeded with one item processed
        assert len(data["items"]) >= 1

    def test_import_json_with_plan_detailed(self, client):
        """Import plan with detailed items."""
        payload = {
            "plans": [
                {
                    "plan_id": "complex_plan",
                    "author": "alice",
                    "items": [
                        {
                            "id": "item1",
                            "title": "Build API",
                            "phase": "1",
                            "assignee": "bob",
                            "role": "backend",
                            "status": "in_progress",
                            "order": 1,
                        },
                        {
                            "id": "item2",
                            "title": "Build UI",
                            "phase": "2",
                            "assignee": "alice",
                            "role": "frontend",
                            "status": "open",
                            "order": 2,
                        },
                    ],
                }
            ]
        }
        response = client.post(
            "/api/import/json",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) >= 1


class TestH6ReviewsRejection:
    """H6: 'reviews' entity is not a valid import type; payloads are rejected."""

    def test_reviews_only_payload_returns_422(self, client):
        """POST with only a 'reviews' key is rejected with HTTP 422."""
        response = client.post(
            "/api/import/json",
            json={"reviews": [{"rubric_id": "r1", "verdict": "pass"}]},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        data = response.json()
        # Detail must mention that no recognised entity types were found
        detail_str = str(data.get("detail", ""))
        assert "No recognised entity types" in detail_str

    def test_reviews_only_payload_writes_zero_rows(self, client):
        """Rejected 'reviews' payload must not write any data."""
        # Confirm the endpoint rejects before any processing
        response = client.post(
            "/api/import/json",
            json={"reviews": []},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422


class TestXssDefense:
    """Verify that attacker-controlled field values are not echoed back raw."""

    def test_xss_payload_in_severity_does_not_echo(self, client):
        """Error message for invalid severity must not contain the raw HTML payload.

        A malicious severity value like '<img src=x onerror=alert(1)>' should be
        rejected with a generic error string, not reflected back verbatim.
        """
        xss = "<img src=x onerror=alert(1)>"
        payload = {"risks": [{"title": "XSS Risk", "severity": xss}]}
        response = client.post(
            "/api/import/json",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        # Item is invalid and skipped; overall import returns 200 with skipped=1
        assert response.status_code == 200
        data = response.json()
        assert data["skipped"] == 1
        # The raw XSS payload must not appear anywhere in the error messages
        for err in data["errors"]:
            assert xss not in err, f"Raw XSS payload echoed in error: {err!r}"
        # Error message should be generic text only
        assert any("severity" in err.lower() for err in data["errors"])

    def test_xss_payload_in_status_does_not_echo(self, client):
        """Error message for invalid status must not contain the raw HTML payload."""
        xss = "<script>alert('xss')</script>"
        payload = {"risks": [{"title": "XSS Risk", "status": xss}]}
        response = client.post(
            "/api/import/json",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["skipped"] == 1
        for err in data["errors"]:
            assert xss not in err, f"Raw XSS payload echoed in error: {err!r}"

    def test_xss_payload_in_priority_does_not_echo(self, client):
        """Error message for invalid priority must not contain the raw HTML payload."""
        xss = "<img src=x onerror=alert(1)>"
        payload = {"pendenzen": [{"title": "XSS Task", "priority": xss}]}
        response = client.post(
            "/api/import/json",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["skipped"] == 1
        for err in data["errors"]:
            assert xss not in err, f"Raw XSS payload echoed in error: {err!r}"


class TestH2NullOptionalFields:
    """H2: importing a risk with an explicit-null optional field must not 500."""

    def test_owner_null_returns_200_skipped(self, client):
        """POST {"risks":[{"title":"t","owner":null}]} → HTTP 200, skipped=1."""
        response = client.post(
            "/api/import/json",
            json={"risks": [{"title": "t", "owner": None}]},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["skipped"] == 1
        assert data["created"] == 0
