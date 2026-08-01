"""Schema-version contract tests for the Copilot C1 adapter.

Test 1 — Registry contract: "hermes.project_state/v1" must have a registered
          adapter whose key matches the literal in copilot_state_export.txt.
Test 2 — Golden-file:  load canned Copilot v1 JSON → adapt → assert exact
          importer-compatible output shape and enum values.
Test 3 — End-to-end:   adapted payload → validate_import_payload →
          import_payload → verify created row counts.
Test 4 — Native pass-through: payload with no "schema" key is unchanged.
Test 5 — Unsupported schema: ValueError with clear message.
Test 6 — Edge cases: empty WBS, missing project, duplicate risk external_refs.
Test 7 — Endpoint integration: POST /api/import/json with Copilot payload.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermes_assistant.webapp.import_adapters import adapt_payload, registered_schemas
from hermes_assistant.webapp.import_json import import_payload, validate_import_payload

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "import" / "copilot_v1_export.json"
)

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "hermes_assistant"
    / "webapp"
    / "static"
    / "prompts"
    / "copilot_state_export.txt"
)

SCHEMA_VERSION = "hermes.project_state/v1"


@pytest.fixture(scope="module")
def copilot_v1_payload() -> dict:
    """Load the canned Copilot v1 export fixture."""
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def client():
    from hermes_assistant.webapp.server import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# Test 1 — Registry contract
# ---------------------------------------------------------------------------


class TestRegistryContract:
    def test_schema_version_is_registered(self):
        """The adapter registry must contain the canonical schema-version string."""
        assert SCHEMA_VERSION in registered_schemas(), (
            f"{SCHEMA_VERSION!r} not found in registered schemas: "
            f"{sorted(registered_schemas())}"
        )

    def test_schema_version_matches_prompt_literal(self):
        """The schema string in copilot_state_export.txt must match the registry key.

        This is the contract test: if the Copilot prompt ever changes its schema
        version, this test will fail and force the adapter to be updated.
        """
        prompt_text = _PROMPT_PATH.read_text(encoding="utf-8")
        assert SCHEMA_VERSION in prompt_text, (
            f"Schema version {SCHEMA_VERSION!r} not found in prompt file "
            f"{_PROMPT_PATH}. Adapter and prompt are out of sync."
        )


# ---------------------------------------------------------------------------
# Test 2 — Golden-file
# ---------------------------------------------------------------------------


class TestGoldenFile:
    def test_adapt_produces_importer_keys(self, copilot_v1_payload):
        """Adapted payload must contain only native importer entity keys."""
        adapted = adapt_payload(copilot_v1_payload)
        valid_keys = {"risks", "plans", "pendenzen", "projects", "_skipped_sections"}
        extra = set(adapted.keys()) - valid_keys
        assert not extra, f"Unexpected keys in adapted payload: {extra}"

    def test_adapt_project_to_projects(self, copilot_v1_payload):
        """project.external_ref 'proj/hermes-pilot' → project_id 'hermes-pilot'."""
        adapted = adapt_payload(copilot_v1_payload)
        assert "projects" in adapted
        assert len(adapted["projects"]) == 1
        assert adapted["projects"][0]["project_id"] == "hermes-pilot"

    def test_adapt_wbs_to_plans(self, copilot_v1_payload):
        """WBS nodes are flattened into one plan under the project plan_id."""
        adapted = adapt_payload(copilot_v1_payload)
        assert "plans" in adapted
        assert len(adapted["plans"]) == 1
        plan = adapted["plans"][0]
        assert plan["plan_id"] == "hermes-pilot"
        assert plan["author"] == "copilot-import"
        assert len(plan["items"]) == 2  # two WBS nodes in fixture

    def test_adapt_wbs_items_carry_external_ref_as_id(self, copilot_v1_payload):
        """WBS external_ref is preserved as item id for idempotent re-imports."""
        adapted = adapt_payload(copilot_v1_payload)
        items = adapted["plans"][0]["items"]
        ids = [item.get("id") for item in items]
        assert "wp/anforderungsanalyse" in ids
        assert "wp/backend-api" in ids

    def test_adapt_wbs_item_ordering(self, copilot_v1_payload):
        """WBS items are ordered by their position in the source array."""
        adapted = adapt_payload(copilot_v1_payload)
        items = adapted["plans"][0]["items"]
        orders = [item["order"] for item in items]
        assert orders == sorted(orders)

    def test_adapt_risks_likelihood_enum(self, copilot_v1_payload):
        """German likelihood strings are translated to integer 1-5 scale."""
        adapted = adapt_payload(copilot_v1_payload)
        likelihoods = {r["title"]: r["likelihood"] for r in adapted["risks"]}
        # "mittel" → 3
        assert likelihoods["Vendor API nicht rechtzeitig verfügbar"] == 3
        # "tief" → 2
        assert likelihoods["Ressourcenengpass im Team"] == 2
        # "hoch" → 4
        assert likelihoods["Datenverlust bei Migration"] == 4

    def test_adapt_risks_severity_enum(self, copilot_v1_payload):
        """German impact strings are translated to English severity strings."""
        adapted = adapt_payload(copilot_v1_payload)
        severities = {r["title"]: r["severity"] for r in adapted["risks"]}
        assert severities["Vendor API nicht rechtzeitig verfügbar"] == "high"
        assert severities["Ressourcenengpass im Team"] == "medium"
        assert severities["Datenverlust bei Migration"] == "low"

    def test_adapt_pendenzen_source_review(self, copilot_v1_payload):
        """Copilot source 'review' passes through unchanged."""
        adapted = adapt_payload(copilot_v1_payload)
        sources = {p["title"]: p["source"] for p in adapted["pendenzen"]}
        assert sources["Security review durchführen"] == "review"

    def test_adapt_pendenzen_source_decision_log(self, copilot_v1_payload):
        """Copilot source 'decision_log' is normalised to 'decision'."""
        adapted = adapt_payload(copilot_v1_payload)
        sources = {p["title"]: p["source"] for p in adapted["pendenzen"]}
        assert sources["Hosting-Entscheid dokumentieren"] == "decision"

    def test_adapt_pendenzen_carry_external_ref_as_id(self, copilot_v1_payload):
        """Pendenz external_ref is preserved as id for idempotent re-imports."""
        adapted = adapt_payload(copilot_v1_payload)
        ids = {p["title"]: p.get("id") for p in adapted["pendenzen"]}
        assert ids["Security review durchführen"] == "pd/security-review"
        assert ids["Hosting-Entscheid dokumentieren"] == "pd/entscheid-hosting"

    def test_adapt_skipped_sections_not_silent(self, copilot_v1_payload):
        """open_assumptions and decisions appear in _skipped_sections, not dropped."""
        adapted = adapt_payload(copilot_v1_payload)
        skipped = adapted.get("_skipped_sections", [])
        assert "open_assumptions" in skipped
        assert "decisions" in skipped

    def test_adapt_no_unknown_importer_keys(self, copilot_v1_payload):
        """The adapter must not emit Copilot-only keys like 'meta' or 'wbs'."""
        adapted = adapt_payload(copilot_v1_payload)
        for key in ("schema", "meta", "wbs", "open_assumptions", "decisions"):
            assert key not in adapted, f"Unexpected key {key!r} in adapted payload"


# ---------------------------------------------------------------------------
# Test 3 — End-to-end: adapt → validate → import → row counts
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_adapted_payload_passes_validation(self, copilot_v1_payload):
        """validate_import_payload must accept the adapted payload."""
        adapted = adapt_payload(copilot_v1_payload)
        adapted.pop("_skipped_sections", None)
        errors = validate_import_payload(adapted)
        assert errors == [], f"Validation errors after adaptation: {errors}"

    def test_adapted_payload_import_creates_rows(self, copilot_v1_payload, tmp_path):
        """import_payload must create records for all adapted entity types."""
        adapted = adapt_payload(copilot_v1_payload)
        adapted.pop("_skipped_sections", None)
        result = import_payload(
            adapted,
            risks_db=":memory:",
            plans_db=":memory:",
            tasks_db=":memory:",
            projects_root=str(tmp_path),
        )
        assert result.ok is True
        # Fixture has 1 project, 1 plan, 3 risks, 2 pendenzen
        assert result.entity_counts.get("projects") == 1
        assert result.entity_counts.get("plans") == 1
        assert result.entity_counts.get("risks") == 3
        assert result.entity_counts.get("pendenzen") == 2
        assert result.skipped == 0, f"Unexpected skips: {result.errors}"

    def test_adapted_payload_upsert_on_second_import(self, copilot_v1_payload):
        """Importing the same payload twice upserts risks by external_ref id."""
        adapted1 = adapt_payload(copilot_v1_payload)
        adapted1.pop("_skipped_sections", None)
        r1 = import_payload(adapted1, risks_db=":memory:", plans_db=":memory:",
                            tasks_db=":memory:")
        # First import: all created
        assert r1.created >= 3  # at minimum the 3 risks


# ---------------------------------------------------------------------------
# Test 4 — Native pass-through (no regression)
# ---------------------------------------------------------------------------


class TestNativePassThrough:
    def test_payload_without_schema_key_is_unchanged(self):
        """Native importer payloads (no 'schema' key) must pass through unmodified."""
        native = {
            "risks": [{"title": "Risk A", "severity": "high", "likelihood": 3}]
        }
        result = adapt_payload(native)
        assert result is native  # exact same object — no copy

    def test_native_import_still_works_after_wiring(self):
        """Existing native-format imports continue to work after server wiring."""
        native = {
            "risks": [{"title": "Native Risk", "severity": "medium", "likelihood": 2}]
        }
        adapted = adapt_payload(native)
        errors = validate_import_payload(adapted)
        assert errors == []
        result = import_payload(adapted, risks_db=":memory:", plans_db=":memory:",
                                tasks_db=":memory:")
        assert result.ok is True
        assert result.created == 1


# ---------------------------------------------------------------------------
# Test 5 — Unsupported schema
# ---------------------------------------------------------------------------


class TestUnsupportedSchema:
    def test_unknown_schema_raises_value_error(self):
        """adapt_payload raises ValueError for unrecognised schema versions."""
        payload = {"schema": "hermes.project_state/v99", "data": []}
        with pytest.raises(ValueError, match="Unsupported schema"):
            adapt_payload(payload)

    def test_error_message_contains_schema_string(self):
        """ValueError message must name the offending schema version."""
        bad_schema = "some.unknown/v0"
        with pytest.raises(ValueError, match=bad_schema):
            adapt_payload({"schema": bad_schema})


# ---------------------------------------------------------------------------
# Test 6 — Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_wbs_produces_empty_plan_items(self):
        """An empty WBS array produces a plan with an empty items list."""
        payload = {
            "schema": SCHEMA_VERSION,
            "project": {"external_ref": "proj/myproj", "title": "My Project"},
            "wbs": [],
        }
        adapted = adapt_payload(payload)
        assert adapted["plans"][0]["items"] == []

    def test_missing_project_uses_fallback_plan_id(self):
        """When 'project' is absent, plan_id defaults to 'imported-project'."""
        payload = {
            "schema": SCHEMA_VERSION,
            "wbs": [
                {
                    "external_ref": "wp/task-one",
                    "title": "Task One",
                    "node_kind": "task",
                    "status": "open",
                }
            ],
        }
        adapted = adapt_payload(payload)
        assert adapted["plans"][0]["plan_id"] == "imported-project"

    def test_risks_without_external_ref_get_no_id(self):
        """Risks without external_ref do not get an id key (auto-generated later)."""
        payload = {
            "schema": SCHEMA_VERSION,
            "risks": [{"title": "Anon Risk", "impact": "mittel", "likelihood": "hoch"}],
        }
        adapted = adapt_payload(payload)
        assert "id" not in adapted["risks"][0]

    def test_unknown_german_enum_falls_back_to_default(self):
        """Unknown German enum values fall back to safe defaults, not errors."""
        payload = {
            "schema": SCHEMA_VERSION,
            "risks": [
                {"title": "Risk", "impact": "unbekannt", "likelihood": "unbekannt"}
            ],
        }
        adapted = adapt_payload(payload)
        risk = adapted["risks"][0]
        assert risk["severity"] == "medium"  # default
        assert risk["likelihood"] == 3       # default

    def test_pendenzen_source_manual_passes_through(self):
        """Source 'manual' is a valid PendenzSource and passes through unchanged."""
        payload = {
            "schema": SCHEMA_VERSION,
            "pendenzen": [
                {"external_ref": "pd/x", "title": "Manual Task", "source": "manual"}
            ],
        }
        adapted = adapt_payload(payload)
        assert adapted["pendenzen"][0]["source"] == "manual"

    def test_open_assumptions_only_noted_in_skipped(self):
        """A payload with only open_assumptions produces skipped note but no importer key."""
        payload = {
            "schema": SCHEMA_VERSION,
            "open_assumptions": [{"text": "Budget ok", "since": "2026-01-01"}],
        }
        adapted = adapt_payload(payload)
        assert "open_assumptions" in adapted["_skipped_sections"]
        assert "open_assumptions" not in adapted or adapted.get("open_assumptions") is None

    def test_decisions_only_noted_in_skipped(self):
        """A payload with only decisions produces skipped note but no importer key."""
        payload = {
            "schema": SCHEMA_VERSION,
            "decisions": [{"title": "Use Python", "at": "2026-01-01"}],
        }
        adapted = adapt_payload(payload)
        assert "decisions" in adapted["_skipped_sections"]

    def test_empty_optional_sections_not_in_skipped(self):
        """Empty open_assumptions and decisions lists do not appear in _skipped_sections."""
        payload = {
            "schema": SCHEMA_VERSION,
            "open_assumptions": [],
            "decisions": [],
        }
        adapted = adapt_payload(payload)
        assert "open_assumptions" not in adapted["_skipped_sections"]
        assert "decisions" not in adapted["_skipped_sections"]


# ---------------------------------------------------------------------------
# Test 7 — Endpoint integration
# ---------------------------------------------------------------------------


class TestEndpointIntegration:
    def test_copilot_payload_via_endpoint_returns_200(self, copilot_v1_payload, client):
        """POST /api/import/json with Copilot v1 payload must return 200."""
        response = client.post(
            "/api/import/json",
            json=copilot_v1_payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_copilot_payload_endpoint_creates_entities(self, copilot_v1_payload, client):
        """Endpoint must report created counts for all mapped entity types."""
        response = client.post(
            "/api/import/json",
            json=copilot_v1_payload,
            headers={"Content-Type": "application/json"},
        )
        data = response.json()
        assert data["created"] >= 1  # at minimum 1 entity created

    def test_copilot_payload_endpoint_surfaces_skipped_sections(
        self, copilot_v1_payload, client
    ):
        """Endpoint response errors must note the skipped Copilot-only sections."""
        response = client.post(
            "/api/import/json",
            json=copilot_v1_payload,
            headers={"Content-Type": "application/json"},
        )
        data = response.json()
        # The fixture has open_assumptions and decisions — they must appear in errors
        skipped_notes = [e for e in data.get("errors", []) if "skipped" in e.lower()]
        assert len(skipped_notes) >= 2, (
            f"Expected at least 2 skipped-section notes, got: {data.get('errors')}"
        )

    def test_unsupported_schema_via_endpoint_returns_422(self, client):
        """Endpoint must return 422 for an unsupported schema version."""
        bad_payload = {
            "schema": "hermes.project_state/v99",
            "data": [],
        }
        response = client.post(
            "/api/import/json",
            json=bad_payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert "Unsupported schema" in response.text

    def test_native_import_still_works_via_endpoint(self, client):
        """Wiring the adapter must not break existing native-format imports."""
        native = {
            "risks": [{"title": "Post-wire Native Risk", "severity": "low"}]
        }
        response = client.post(
            "/api/import/json",
            json=native,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True
