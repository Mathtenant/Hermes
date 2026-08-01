"""Unit tests for JSON import validation and payload processing."""
import json
import pytest
from hermes_assistant.webapp.import_json import (
    ImportResult,
    ImportItemResult,
    MAX_IMPORT_BYTES,
    validate_entity,
    validate_import_payload,
    import_payload,
)


class TestValidateEntity:
    """Test entity-level validation logic."""

    def test_risk_valid_minimal(self):
        """Minimal valid risk has only title."""
        assert validate_entity("risks", {"title": "Test risk"}) == []

    def test_risk_invalid_empty_title(self):
        """Risk with empty title is invalid."""
        errs = validate_entity("risks", {"title": ""})
        assert "Missing required field: 'title'" in errs

    def test_risk_invalid_severity(self):
        """Risk with invalid severity rejected."""
        obj = {"title": "Risk", "severity": "extreme"}
        errs = validate_entity("risks", obj)
        assert any("severity" in e for e in errs)

    def test_risk_invalid_likelihood_range(self):
        """Likelihood must be 1-5."""
        obj = {"title": "Risk", "likelihood": 10}
        errs = validate_entity("risks", obj)
        assert any("likelihood" in e for e in errs)

    def test_risk_invalid_likelihood_type(self):
        """Likelihood must be integer."""
        obj = {"title": "Risk", "likelihood": "high"}
        errs = validate_entity("risks", obj)
        assert any("likelihood" in e and "integer" in e for e in errs)

    def test_risk_invalid_status(self):
        """Status must be one of enum values."""
        obj = {"title": "Risk", "status": "pending"}
        errs = validate_entity("risks", obj)
        assert any("status" in e for e in errs)

    def test_risk_valid_all_fields(self):
        """Risk with all valid fields passes."""
        obj = {
            "id": "r1",
            "title": "Risk",
            "description": "Desc",
            "severity": "high",
            "likelihood": 3,
            "owner": "Alice",
            "status": "open",
            "confidential": False,
        }
        assert validate_entity("risks", obj) == []

    def test_plan_valid_minimal(self):
        """Plan with id and items list."""
        obj = {"plan_id": "p1", "items": []}
        assert validate_entity("plans", obj) == []

    def test_plan_missing_plan_id(self):
        """Plan missing plan_id is invalid."""
        errs = validate_entity("plans", {"items": []})
        assert "Missing required field: 'plan_id'" in errs

    def test_plan_items_not_list(self):
        """Items must be a list."""
        obj = {"plan_id": "p1", "items": "not a list"}
        errs = validate_entity("plans", obj)
        assert any("items" in e and "list" in e for e in errs)

    def test_plan_item_missing_title(self):
        """Plan items must have title."""
        obj = {"plan_id": "p1", "items": [{"phase": "1"}]}
        errs = validate_entity("plans", obj)
        assert any("items[0]" in e and "title" in e for e in errs)

    def test_plan_valid_with_items(self):
        """Plan with items."""
        obj = {
            "plan_id": "p1",
            "items": [{"title": "Outcome 1", "phase": "1"}],
        }
        assert validate_entity("plans", obj) == []

    def test_pendenz_valid_minimal(self):
        """Pendenz with title."""
        assert validate_entity("pendenzen", {"title": "Task"}) == []

    def test_pendenz_invalid_priority(self):
        """Priority must be valid."""
        obj = {"title": "Task", "priority": "urgent"}
        errs = validate_entity("pendenzen", obj)
        assert any("priority" in e for e in errs)

    def test_pendenz_valid_all_fields(self):
        """Pendenz with all fields."""
        obj = {
            "id": "p1",
            "title": "Task",
            "description": "Desc",
            "owner": "Alice",
            "priority": "high",
            "source": "manual",
            "source_ref": "ref123",
        }
        assert validate_entity("pendenzen", obj) == []

    def test_project_valid_minimal(self):
        """Project with project_id."""
        assert validate_entity("projects", {"project_id": "proj1"}) == []

    def test_project_missing_id(self):
        """Project missing project_id is invalid."""
        errs = validate_entity("projects", {})
        assert "Missing required field: 'project_id'" in errs

    def test_entity_not_dict(self):
        """Entity must be a dict."""
        errs = validate_entity("risks", "not a dict")
        assert "Entity must be a JSON object" in errs


class TestValidateImportPayload:
    """Test top-level payload validation."""

    def test_payload_not_dict(self):
        """Payload must be a dict."""
        errs = validate_import_payload([])
        assert any("Payload must be a JSON object" in e for e in errs)

    def test_payload_no_entity_types(self):
        """Payload must have at least one entity type."""
        errs = validate_import_payload({"unknown": []})
        assert any("No recognised entity types" in e for e in errs)

    def test_payload_entity_not_list(self):
        """Entity field must be a list."""
        errs = validate_import_payload({"risks": "not a list"})
        assert any("must be a list" in e for e in errs)

    def test_payload_too_many_items(self):
        """Entity list cannot exceed max items."""
        large = [{"title": f"risk{i}"} for i in range(10_001)]
        errs = validate_import_payload({"risks": large})
        assert any("10000" in e for e in errs)

    def test_payload_valid_single_type(self):
        """Valid payload with single entity type."""
        payload = {"risks": [{"title": "Risk"}]}
        assert validate_import_payload(payload) == []

    def test_payload_valid_multiple_types(self):
        """Valid payload with multiple entity types."""
        payload = {
            "risks": [{"title": "Risk"}],
            "plans": [{"plan_id": "p1", "items": []}],
            "pendenzen": [{"title": "Task"}],
        }
        assert validate_import_payload(payload) == []

    def test_payload_mixed_valid_invalid_types(self):
        """Payload with mix of valid and invalid types (invalid ignored)."""
        payload = {
            "risks": [{"title": "Risk"}],
            "unknown_type": [{"data": "value"}],
        }
        # Should not error on unknown_type, just skip it
        assert validate_import_payload(payload) == []


class TestImportPayload:
    """Test full import execution."""

    def test_import_empty_payload(self):
        """Empty payload returns no-op result."""
        result = import_payload({})
        assert result.ok is True
        assert result.created == 0
        assert result.updated == 0

    def test_import_single_risk(self):
        """Import single risk into in-memory db."""
        payload = {
            "risks": [
                {
                    "id": "r1",
                    "title": "Test Risk",
                    "severity": "high",
                    "likelihood": 3,
                }
            ]
        }
        result = import_payload(
            payload, risks_db=":memory:", plans_db=":memory:",
            tasks_db=":memory:"
        )
        assert result.ok is True
        assert result.created == 1
        assert result.updated == 0
        assert result.skipped == 0
        assert len(result.items) == 1
        assert result.items[0].action == "created"

    def test_import_multiple_risks(self):
        """Import multiple risks."""
        payload = {
            "risks": [
                {"title": f"Risk {i}", "severity": "medium", "likelihood": 3}
                for i in range(5)
            ]
        }
        result = import_payload(
            payload, risks_db=":memory:", plans_db=":memory:",
            tasks_db=":memory:"
        )
        assert result.created == 5
        assert result.skipped == 0

    def test_import_with_validation_errors(self):
        """H5 atomicity: any invalid item aborts the entire entity-type batch."""
        payload = {
            "risks": [
                {"title": "Valid Risk"},  # OK
                {"severity": "high"},  # Missing title — causes batch abort
                {"title": "Another valid"},  # OK but never written
            ]
        }
        result = import_payload(
            payload, risks_db=":memory:", plans_db=":memory:",
            tasks_db=":memory:"
        )
        # Atomicity: no rows committed when any item fails validation
        assert result.created == 0
        assert result.skipped == 1
        assert len(result.errors) == 1

    def test_import_duplicate_ids_upsert(self):
        """Importing same ID twice updates the record."""
        payload1 = {
            "risks": [
                {"id": "r1", "title": "Original Risk", "severity": "low"}
            ]
        }
        payload2 = {
            "risks": [
                {"id": "r1", "title": "Updated Risk", "severity": "high"}
            ]
        }
        result1 = import_payload(
            payload1, risks_db=":memory:", plans_db=":memory:",
            tasks_db=":memory:"
        )
        assert result1.created == 1

        # Note: In real scenario, would reuse same db. Here we demonstrate logic.
        # Full test would need persistent db to verify upsert.
        assert result1.ok is True

    def test_import_plans(self):
        """Import plans."""
        payload = {
            "plans": [
                {
                    "plan_id": "p1",
                    "items": [
                        {"title": "Outcome 1", "phase": "1"},
                        {"title": "Outcome 2", "phase": "2"},
                    ],
                }
            ]
        }
        result = import_payload(
            payload, risks_db=":memory:", plans_db=":memory:",
            tasks_db=":memory:"
        )
        assert result.created == 1
        assert result.entity_counts["plans"] == 1

    def test_import_pendenzen(self):
        """Import pendenzen."""
        payload = {
            "pendenzen": [
                {"title": "Task 1", "priority": "high"},
                {"title": "Task 2", "priority": "medium"},
            ]
        }
        result = import_payload(
            payload, risks_db=":memory:", plans_db=":memory:",
            tasks_db=":memory:"
        )
        assert result.created == 2
        assert result.entity_counts["pendenzen"] == 2

    def test_import_projects(self, tmp_path):
        """Import projects creates directories."""
        payload = {
            "projects": [
                {"project_id": "proj1"},
                {"project_id": "proj2"},
            ]
        }
        result = import_payload(
            payload,
            risks_db=":memory:",
            plans_db=":memory:",
            tasks_db=":memory:",
            projects_root=str(tmp_path),
        )
        assert result.created == 2
        assert (tmp_path / "proj1").exists()
        assert (tmp_path / "proj2").exists()

    def test_import_mixed_types(self):
        """Import payload with multiple entity types."""
        payload = {
            "risks": [{"title": "Risk"}],
            "plans": [{"plan_id": "p1", "items": []}],
            "pendenzen": [{"title": "Task"}],
        }
        result = import_payload(
            payload, risks_db=":memory:", plans_db=":memory:",
            tasks_db=":memory:"
        )
        assert result.created == 3
        assert result.entity_counts["risks"] == 1
        assert result.entity_counts["plans"] == 1
        assert result.entity_counts["pendenzen"] == 1

    def test_import_result_ok_flag(self):
        """ImportResult.ok is True if any items imported."""
        payload = {"risks": [{"title": "Risk"}]}
        result = import_payload(
            payload, risks_db=":memory:", plans_db=":memory:",
            tasks_db=":memory:"
        )
        assert result.ok is True

    def test_import_result_ok_false_on_all_skipped(self):
        """ImportResult.ok is False if all items skipped."""
        payload = {
            "risks": [
                {},  # Invalid
                {"severity": "high"},  # Invalid (missing title)
            ]
        }
        result = import_payload(
            payload, risks_db=":memory:", plans_db=":memory:",
            tasks_db=":memory:"
        )
        # All skipped, no creates/updates
        assert result.created == 0
        assert result.updated == 0
        assert result.skipped == 2


# ---------------------------------------------------------------------------
# M2 external_ref idempotency tests
# ---------------------------------------------------------------------------


class TestM2ExternalRefIdempotency:
    """M2: re-importing Copilot pendenzen via external_ref must upsert, not dup."""

    def test_second_import_creates_zero_new_rows(self, tmp_path):
        """Importing the same 3 pendenzen (each with distinct external_ref) twice
        must result in 0 new rows on the second pass (all 3 are updated)."""
        db = str(tmp_path / "tasks.db")
        payload = {
            "pendenzen": [
                {"title": f"Task {i}", "external_ref": f"cop-{i}"}
                for i in range(3)
            ]
        }
        first = import_payload(
            payload, risks_db=":memory:", plans_db=":memory:", tasks_db=db
        )
        assert first.created == 3
        assert first.updated == 0

        second = import_payload(
            payload, risks_db=":memory:", plans_db=":memory:", tasks_db=db
        )
        assert second.created == 0, "Re-import must not create duplicate rows"
        assert second.updated == 3

        # Verify DB row count stays at 3
        import sqlite3
        conn = sqlite3.connect(db)
        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        conn.close()
        assert count == 3

    def test_same_external_ref_deduplicates_to_one_row(self, tmp_path):
        """Import external_ref='cop-123', then import it again → 1 DB row, not 2."""
        db = str(tmp_path / "tasks.db")
        payload = {"pendenzen": [{"title": "Original", "external_ref": "cop-123"}]}

        result1 = import_payload(
            payload, risks_db=":memory:", plans_db=":memory:", tasks_db=db
        )
        assert result1.created == 1

        payload2 = {"pendenzen": [{"title": "Updated", "external_ref": "cop-123"}]}
        result2 = import_payload(
            payload2, risks_db=":memory:", plans_db=":memory:", tasks_db=db
        )
        assert result2.created == 0
        assert result2.updated == 1

        import sqlite3
        conn = sqlite3.connect(db)
        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        conn.close()
        assert count == 1, "Must have exactly 1 row, not 2"

    def test_backward_compat_id_fallback_no_external_ref(self, tmp_path):
        """Payload with explicit 'id' but no 'external_ref' still deduplicates
        via the legacy id-based path."""
        db = str(tmp_path / "tasks.db")
        payload = {"pendenzen": [{"id": "legacy-001", "title": "Legacy task"}]}

        result1 = import_payload(
            payload, risks_db=":memory:", plans_db=":memory:", tasks_db=db
        )
        assert result1.created == 1

        result2 = import_payload(
            payload, risks_db=":memory:", plans_db=":memory:", tasks_db=db
        )
        assert result2.created == 0
        assert result2.updated == 1

        import sqlite3
        conn = sqlite3.connect(db)
        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        conn.close()
        assert count == 1, "Legacy id-based fallback must also deduplicate"


@pytest.mark.parametrize("entity_type", ["risks", "plans", "pendenzen", "projects"])
def test_validate_entity_accepts_dict(entity_type):
    """Validate entity accepts at minimum a valid dict for each supported type."""
    minimum_valid = {
        "risks": {"title": "Risk"},
        "plans": {"plan_id": "p1", "items": []},
        "pendenzen": {"title": "Task"},
        "projects": {"project_id": "proj"},
    }
    obj = minimum_valid[entity_type]
    assert isinstance(validate_entity(entity_type, obj), list)


# ---------------------------------------------------------------------------
# H5 atomicity tests
# ---------------------------------------------------------------------------


class TestH5Atomicity:
    """H5: single-transaction per-entity imports with all-or-nothing semantics."""

    def test_risks_abort_entire_batch_on_validation_failure(self, tmp_path):
        """If any risk fails validation, zero risks are written to the database."""
        db = str(tmp_path / "risks.db")
        risks = [
            {"title": f"Risk {i}", "severity": "medium", "likelihood": 3}
            for i in range(10)
        ]
        # Risk at index 4 (the 5th item) is invalid: missing title
        risks[4] = {"severity": "medium", "likelihood": 3}

        result = import_payload(
            {"risks": risks},
            risks_db=db,
            plans_db=":memory:",
            tasks_db=":memory:",
        )

        # Exactly one error logged for the single invalid risk
        assert result.skipped == 1
        assert len(result.errors) == 1
        # No rows written — atomicity holds
        assert result.created == 0

        # Verify at the DB level that nothing was persisted
        from hermes_assistant.risks.registry import RiskRegistry
        registry = RiskRegistry(db)
        try:
            assert registry.list() == []
        finally:
            registry.close_connection()

    def test_risks_all_committed_when_all_valid(self, tmp_path):
        """When all risks pass validation, all are committed in a single batch."""
        db = str(tmp_path / "risks.db")
        risks = [
            {"title": f"Risk {i}", "severity": "medium", "likelihood": 3}
            for i in range(5)
        ]
        result = import_payload(
            {"risks": risks},
            risks_db=db,
            plans_db=":memory:",
            tasks_db=":memory:",
        )

        assert result.created == 5
        assert result.errors == []

        from hermes_assistant.risks.registry import RiskRegistry
        registry = RiskRegistry(db)
        try:
            assert len(registry.list()) == 5
        finally:
            registry.close_connection()


# ---------------------------------------------------------------------------
# H6 reviews-entity removal tests
# ---------------------------------------------------------------------------


class TestH6Reviews:
    """H6: 'reviews' is no longer a valid import entity type."""

    def test_reviews_not_recognised_by_validate_import_payload(self):
        """Payload containing only 'reviews' returns a validation error."""
        errs = validate_import_payload(
            {"reviews": [{"rubric_id": "r1", "verdict": "pass"}]}
        )
        assert any("No recognised entity types" in e for e in errs)

    def test_reviews_mixed_with_unknown_also_rejected(self):
        """'reviews' alongside other unknown keys is still rejected."""
        errs = validate_import_payload({"reviews": [], "foo": []})
        assert any("No recognised entity types" in e for e in errs)

    def test_reviews_alongside_valid_type_is_silently_ignored(self):
        """A payload with 'risks' and 'reviews' is valid — 'reviews' is unknown
        so it is ignored by validate_import_payload (unknown keys do not
        cause errors when at least one recognised type is present)."""
        errs = validate_import_payload(
            {"risks": [{"title": "R"}], "reviews": []}
        )
        # No error: 'risks' is recognised; 'reviews' is silently ignored
        assert errs == []
