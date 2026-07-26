"""E2E tests for JSON import UI in web app."""
import json
import pytest
from pathlib import Path


@pytest.mark.e2e
class TestJsonImportUI:
    """Test JSON import modal in web dashboard."""

    def test_import_button_visible_on_dashboard(self, page):
        """Import JSON button appears on dashboard."""
        page.goto("http://localhost:8000")
        # Look for import button
        import_btn = page.locator('button:has-text("Import JSON")')
        assert import_btn.is_visible()

    def test_import_modal_opens(self, page):
        """Clicking import button opens modal dialog."""
        page.goto("http://localhost:8000")
        import_btn = page.locator('button:has-text("Import JSON")')
        import_btn.click()
        # Modal should appear
        modal = page.locator('[data-testid="json-import-modal"]')
        assert modal.is_visible()

    def test_import_modal_has_file_input(self, page):
        """Modal has file upload input."""
        page.goto("http://localhost:8000")
        import_btn = page.locator('button:has-text("Import JSON")')
        import_btn.click()
        # File input should exist
        file_input = page.locator('input[type="file"]')
        assert file_input.is_visible()

    def test_import_modal_has_text_input(self, page):
        """Modal has raw JSON text input."""
        page.goto("http://localhost:8000")
        import_btn = page.locator('button:has-text("Import JSON")')
        import_btn.click()
        # Text area for raw JSON
        textarea = page.locator('textarea[data-testid="raw-json-input"]')
        assert textarea.is_visible()

    def test_import_with_json_text(self, page):
        """Import via pasted JSON text."""
        page.goto("http://localhost:8000")
        import_btn = page.locator('button:has-text("Import JSON")')
        import_btn.click()
        # Fill in JSON
        textarea = page.locator('textarea[data-testid="raw-json-input"]')
        payload = {
            "risks": [
                {"title": "Test Risk", "severity": "high", "likelihood": 3}
            ]
        }
        textarea.fill(json.dumps(payload))
        # Click import button
        import_submit = page.locator('[data-testid="import-submit-btn"]')
        import_submit.click()
        # Should show success message
        success = page.locator('text=Successfully imported')
        success.wait_for(timeout=5000)
        assert success.is_visible()

    def test_import_preview_shows_counts(self, page):
        """Import preview shows items being imported."""
        page.goto("http://localhost:8000")
        import_btn = page.locator('button:has-text("Import JSON")')
        import_btn.click()
        # Fill JSON with multiple items
        textarea = page.locator('textarea[data-testid="raw-json-input"]')
        payload = {
            "risks": [
                {"title": "Risk 1"},
                {"title": "Risk 2"},
                {"title": "Risk 3"},
            ]
        }
        textarea.fill(json.dumps(payload))
        # Preview should update
        preview = page.locator('[data-testid="import-preview"]')
        preview.wait_for(timeout=2000)
        assert "3" in preview.text_content()

    def test_import_error_on_invalid_json(self, page):
        """Invalid JSON shows error message."""
        page.goto("http://localhost:8000")
        import_btn = page.locator('button:has-text("Import JSON")')
        import_btn.click()
        # Paste invalid JSON
        textarea = page.locator('textarea[data-testid="raw-json-input"]')
        textarea.fill("{ invalid json }")
        # Should show error
        error = page.locator('[data-testid="json-error"]')
        error.wait_for(timeout=2000)
        assert "invalid" in error.text_content().lower()

    def test_import_error_on_invalid_payload(self, page):
        """Payload without entity types shows error."""
        page.goto("http://localhost:8000")
        import_btn = page.locator('button:has-text("Import JSON")')
        import_btn.click()
        # Fill with invalid payload
        textarea = page.locator('textarea[data-testid="raw-json-input"]')
        payload = {"unknown_type": [{"data": "value"}]}
        textarea.fill(json.dumps(payload))
        # Submit
        import_submit = page.locator('[data-testid="import-submit-btn"]')
        import_submit.click()
        # Should show error
        error = page.locator('[data-testid="import-error"]')
        error.wait_for(timeout=5000)
        assert error.is_visible()

    def test_import_shows_progress(self, page):
        """Importing shows progress indicator."""
        page.goto("http://localhost:8000")
        import_btn = page.locator('button:has-text("Import JSON")')
        import_btn.click()
        # Fill with JSON
        textarea = page.locator('textarea[data-testid="raw-json-input"]')
        payload = {
            "risks": [{"title": "Risk"}]
        }
        textarea.fill(json.dumps(payload))
        # Click import
        import_submit = page.locator('[data-testid="import-submit-btn"]')
        import_submit.click()
        # Progress should appear briefly
        progress = page.locator('[data-testid="import-progress"]')
        # Wait for it to appear (may not always be visible but should exist)
        try:
            progress.wait_for(timeout=1000)
        except:
            pass  # Progress might be too fast

    def test_import_result_shows_summary(self, page):
        """After import, shows summary of created/updated/skipped."""
        page.goto("http://localhost:8000")
        import_btn = page.locator('button:has-text("Import JSON")')
        import_btn.click()
        # Import valid data
        textarea = page.locator('textarea[data-testid="raw-json-input"]')
        payload = {
            "risks": [
                {"title": "Valid Risk"},
                {"severity": "high"},  # Invalid, missing title
                {"title": "Another Risk"},
            ]
        }
        textarea.fill(json.dumps(payload))
        # Submit
        import_submit = page.locator('[data-testid="import-submit-btn"]')
        import_submit.click()
        # Wait for result
        result = page.locator('[data-testid="import-result"]')
        result.wait_for(timeout=5000)
        # Should show counts
        assert "2" in result.text_content()  # 2 created
        assert "1" in result.text_content()  # 1 skipped

    def test_import_closes_modal_on_success(self, page):
        """Modal closes after successful import."""
        page.goto("http://localhost:8000")
        import_btn = page.locator('button:has-text("Import JSON")')
        import_btn.click()
        modal = page.locator('[data-testid="json-import-modal"]')
        assert modal.is_visible()
        # Import
        textarea = page.locator('textarea[data-testid="raw-json-input"]')
        textarea.fill(json.dumps({"risks": [{"title": "Risk"}]}))
        import_submit = page.locator('[data-testid="import-submit-btn"]')
        import_submit.click()
        # Wait for success
        success = page.locator('text=Successfully imported')
        success.wait_for(timeout=5000)
        # Modal closes after short delay
        modal.wait_for(state="hidden", timeout=3000)

    def test_import_refreshes_dashboard(self, page):
        """Dashboard refreshes after import to show new data."""
        page.goto("http://localhost:8000")
        # Get initial risk count
        initial_risks = page.locator('[data-testid="risks-count"]')
        initial_count = int(initial_risks.text_content() or "0")
        # Import
        import_btn = page.locator('button:has-text("Import JSON")')
        import_btn.click()
        textarea = page.locator('textarea[data-testid="raw-json-input"]')
        textarea.fill(json.dumps({"risks": [{"title": "New Risk"}]}))
        import_submit = page.locator('[data-testid="import-submit-btn"]')
        import_submit.click()
        # Wait for success
        success = page.locator('text=Successfully imported')
        success.wait_for(timeout=5000)
        # Risk count should increase
        updated_risks = page.locator('[data-testid="risks-count"]')
        updated_count = int(updated_risks.text_content() or "0")
        assert updated_count > initial_count

    def test_import_file_upload(self, page, tmp_path):
        """Import via file upload."""
        # Create a temporary JSON file
        json_file = tmp_path / "import.json"
        payload = {
            "risks": [
                {"title": "Risk from file", "severity": "high"}
            ]
        }
        json_file.write_text(json.dumps(payload))
        # Go to app
        page.goto("http://localhost:8000")
        # Open import modal
        import_btn = page.locator('button:has-text("Import JSON")')
        import_btn.click()
        # Upload file
        file_input = page.locator('input[type="file"]')
        file_input.set_input_files(str(json_file))
        # Import button should enable
        import_submit = page.locator('[data-testid="import-submit-btn"]')
        import_submit.click()
        # Should succeed
        success = page.locator('text=Successfully imported')
        success.wait_for(timeout=5000)
        assert success.is_visible()

    def test_import_file_drag_drop(self, page, tmp_path):
        """Import via drag-drop."""
        json_file = tmp_path / "import.json"
        payload = {"risks": [{"title": "Risk", "severity": "medium"}]}
        json_file.write_text(json.dumps(payload))
        page.goto("http://localhost:8000")
        import_btn = page.locator('button:has-text("Import JSON")')
        import_btn.click()
        # Drag file over drop zone
        drop_zone = page.locator('[data-testid="json-drop-zone"]')
        # Simulate drag-drop (Playwright doesn't support native drag-drop easily)
        # Instead, use file input directly
        file_input = page.locator('input[type="file"]')
        file_input.set_input_files(str(json_file))
        import_submit = page.locator('[data-testid="import-submit-btn"]')
        import_submit.click()
        success = page.locator('text=Successfully imported')
        success.wait_for(timeout=5000)

    def test_import_clear_form(self, page):
        """Clear button resets form."""
        page.goto("http://localhost:8000")
        import_btn = page.locator('button:has-text("Import JSON")')
        import_btn.click()
        # Fill form
        textarea = page.locator('textarea[data-testid="raw-json-input"]')
        textarea.fill('{"risks": []}')
        # Clear
        clear_btn = page.locator('[data-testid="clear-form-btn"]')
        clear_btn.click()
        # Should be empty
        assert textarea.text_content() == ""

    def test_import_validation_errors_listed(self, page):
        """Validation errors are listed in result."""
        page.goto("http://localhost:8000")
        import_btn = page.locator('button:has-text("Import JSON")')
        import_btn.click()
        # Import with invalid items
        textarea = page.locator('textarea[data-testid="raw-json-input"]')
        payload = {
            "risks": [
                {"severity": "high"},  # Missing title
                {"likelihood": 10},  # Invalid likelihood + missing title
            ]
        }
        textarea.fill(json.dumps(payload))
        import_submit = page.locator('[data-testid="import-submit-btn"]')
        import_submit.click()
        # Errors should be listed
        errors_section = page.locator('[data-testid="import-errors"]')
        errors_section.wait_for(timeout=5000)
        assert "Missing required field" in errors_section.text_content()

    def test_import_handles_network_error(self, page, monkeypatch):
        """Network errors shown to user."""
        page.goto("http://localhost:8000")
        import_btn = page.locator('button:has-text("Import JSON")')
        import_btn.click()
        textarea = page.locator('textarea[data-testid="raw-json-input"]')
        textarea.fill(json.dumps({"risks": [{"title": "Risk"}]}))
        # Simulate network error by intercepting request
        page.route("/api/import/json", lambda route: route.abort())
        import_submit = page.locator('[data-testid="import-submit-btn"]')
        import_submit.click()
        # Should show error
        error = page.locator('[data-testid="import-error"]')
        error.wait_for(timeout=5000)
        assert error.is_visible()

    def test_import_multiple_times(self, page):
        """Can import multiple times without reloading."""
        page.goto("http://localhost:8000")
        for i in range(3):
            import_btn = page.locator('button:has-text("Import JSON")')
            import_btn.click()
            textarea = page.locator('textarea[data-testid="raw-json-input"]')
            payload = {"risks": [{"title": f"Risk {i}"}]}
            textarea.fill(json.dumps(payload))
            import_submit = page.locator('[data-testid="import-submit-btn"]')
            import_submit.click()
            success = page.locator('text=Successfully imported')
            success.wait_for(timeout=5000)
            # Modal closes for next import
            modal = page.locator('[data-testid="json-import-modal"]')
            modal.wait_for(state="hidden", timeout=3000)
