"""E2E tests for the JSON import UI in the web app.

The import dialog is a two-step wizard: step 1 hands over a Copilot prompt,
step 2 accepts the JSON. Tests that exercise the paste/upload behaviour must
advance past step 1 first — see :func:`_open_paste_step`.
"""
import json
import socket

import pytest

BASE_URL = "http://localhost:8000"


def _server_up(host: str = "localhost", port: int = 8000) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


@pytest.fixture(autouse=True)
def _require_server():
    if not _server_up():
        pytest.skip("No server on localhost:8000 for JSON import UI E2E tests")


@pytest.fixture
def browser_context_args(browser_context_args):
    """Grant clipboard permissions so navigator.clipboard.writeText succeeds.

    Playwright's default context denies clipboard access, which would make
    copyPrompt() always hit its catch branch in headless tests.
    """
    return {
        **browser_context_args,
        "permissions": ["clipboard-read", "clipboard-write"],
    }


def _open_modal(page):
    """Open the import wizard and leave it on step 1 (the Copilot prompt)."""
    page.goto(BASE_URL)
    page.locator('button:has-text("Import JSON")').click()
    page.wait_for_selector('[data-testid="json-import-modal"]', timeout=5000)


def _open_paste_step(page):
    """Open the wizard and advance to step 2, where JSON is pasted/uploaded."""
    _open_modal(page)
    page.locator('[data-testid="import-next-btn"]').click()
    page.wait_for_selector('[data-testid="raw-json-input"]', timeout=5000)


def _submit(page, payload):
    """Paste *payload* and click Import."""
    page.locator('[data-testid="raw-json-input"]').fill(json.dumps(payload))
    page.locator('[data-testid="import-submit-btn"]').click()


@pytest.mark.e2e
class TestJsonImportUI:
    """Test the JSON import wizard in the web dashboard."""

    def test_import_button_visible_on_dashboard(self, page):
        """Import JSON button appears on dashboard."""
        page.goto(BASE_URL)
        assert page.locator('button:has-text("Import JSON")').is_visible()

    def test_import_modal_opens(self, page):
        """Clicking import button opens the dialog."""
        _open_modal(page)
        assert page.locator('[data-testid="json-import-modal"]').is_visible()

    def test_import_modal_has_file_input(self, page):
        """Step 2 offers a file upload."""
        _open_paste_step(page)
        page.locator('[data-testid="mode-file"]').click()
        assert page.locator('input[type="file"]').count() == 1

    def test_import_modal_has_text_input(self, page):
        """Step 2 offers a raw JSON text area."""
        _open_paste_step(page)
        assert page.locator('textarea[data-testid="raw-json-input"]').is_visible()

    def test_import_with_json_text(self, page):
        """Import via pasted JSON text."""
        _open_paste_step(page)
        _submit(page, {"risks": [{"title": "Test Risk", "severity": "high",
                                  "likelihood": 3}]})
        success = page.locator("text=Successfully imported")
        success.wait_for(timeout=5000)
        assert success.is_visible()

    def test_import_preview_shows_counts(self, page):
        """Live preview shows how many rows will be imported."""
        _open_paste_step(page)
        page.locator('[data-testid="raw-json-input"]').fill(
            json.dumps({"risks": [{"title": "Risk 1"}, {"title": "Risk 2"},
                                  {"title": "Risk 3"}]})
        )
        preview = page.locator('[data-testid="import-preview"]')
        preview.wait_for(timeout=2000)
        assert "3" in preview.text_content()

    def test_import_error_on_invalid_json(self, page):
        """Invalid JSON shows an inline error while typing."""
        _open_paste_step(page)
        page.locator('[data-testid="raw-json-input"]').fill("{ invalid json }")
        error = page.locator('[data-testid="import-error"]')
        error.wait_for(timeout=2000)
        assert "invalid" in error.text_content().lower()

    def test_import_error_on_invalid_payload(self, page):
        """A payload with no recognised entity type is rejected by the server."""
        _open_paste_step(page)
        _submit(page, {"unknown_type": [{"data": "value"}]})
        error = page.locator('[data-testid="import-error"]')
        error.wait_for(timeout=5000)
        assert error.is_visible()

    def test_import_shows_progress(self, page):
        """A progress indicator exists while the request is in flight."""
        _open_paste_step(page)
        _submit(page, {"risks": [{"title": "Risk"}]})
        # The import may finish before the indicator is sampled; its presence in
        # the DOM is what matters, not catching it mid-flight.
        assert page.locator('[data-testid="import-progress"]').count() == 1

    def test_import_result_is_atomic_per_entity_type(self, page):
        """One invalid row aborts that entity type — no partial writes.

        The importer validates a whole entity list before writing any of it, so
        a batch containing an invalid risk creates nothing. Reporting "2 of 3
        created" here would mean the atomicity guarantee had been lost.
        """
        _open_paste_step(page)
        _submit(page, {"risks": [
            {"title": "Valid Risk"},
            {"severity": "high"},          # invalid: no title
            {"title": "Another Risk"},
        ]})
        result = page.locator('[data-testid="import-result"]')
        result.wait_for(timeout=5000)
        assert "failed" in result.text_content().lower()
        errors = page.locator('[data-testid="import-errors"]')
        assert "Missing required field" in errors.text_content()

    def test_modal_stays_open_so_warnings_can_be_read(self, page):
        """The dialog deliberately stays open after a successful import.

        An import can succeed while still reporting warnings — redacted email
        addresses, skipped sections — and auto-closing would hide them.
        """
        _open_paste_step(page)
        _submit(page, {"risks": [{"title": "Risk"}]})
        page.locator("text=Successfully imported").wait_for(timeout=5000)
        page.wait_for_timeout(1500)
        assert page.locator('[data-testid="json-import-modal"]').is_visible()

    def test_import_refreshes_dashboard(self, page):
        """Dashboard data reloads after a successful import."""
        page.goto(BASE_URL)
        page.wait_for_selector('[data-testid="risks-count"]', timeout=5000)
        before = int(page.locator('[data-testid="risks-count"]').text_content() or "0")

        page.locator('button:has-text("Import JSON")').click()
        page.locator('[data-testid="import-next-btn"]').click()
        page.wait_for_selector('[data-testid="raw-json-input"]', timeout=5000)
        _submit(page, {"risks": [{"title": "New Risk For Refresh"}]})
        page.locator("text=Successfully imported").wait_for(timeout=5000)

        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        after = int(page.locator('[data-testid="risks-count"]').text_content() or "0")
        assert after > before

    def test_import_file_upload(self, page, tmp_path):
        """Import via file upload."""
        json_file = tmp_path / "import.json"
        json_file.write_text(
            json.dumps({"risks": [{"title": "Risk from file", "severity": "high"}]})
        )
        _open_paste_step(page)
        page.locator('[data-testid="mode-file"]').click()
        page.locator('input[type="file"]').set_input_files(str(json_file))
        page.wait_for_timeout(300)
        page.locator('[data-testid="import-submit-btn"]').click()
        success = page.locator("text=Successfully imported")
        success.wait_for(timeout=5000)
        assert success.is_visible()

    def test_import_drop_zone_present(self, page):
        """File mode shows a drop zone.

        Native drag-and-drop is not scriptable in Playwright, so this covers
        the zone's presence; the file-picker path above covers the upload.
        """
        _open_paste_step(page)
        page.locator('[data-testid="mode-file"]').click()
        assert page.locator('[data-testid="json-drop-zone"]').is_visible()

    def test_import_clear_form(self, page):
        """Clear button empties the pasted JSON."""
        _open_paste_step(page)
        textarea = page.locator('[data-testid="raw-json-input"]')
        textarea.fill('{"risks": []}')
        page.locator('[data-testid="clear-form-btn"]').click()
        page.wait_for_timeout(200)
        # input_value(), not text_content(): the textarea is bound with v-model,
        # so its live value never appears in the element's text content.
        assert textarea.input_value() == ""

    def test_import_validation_errors_listed(self, page):
        """Per-row validation errors are listed in the result."""
        _open_paste_step(page)
        _submit(page, {"risks": [{"severity": "high"}, {"likelihood": 10}]})
        errors_section = page.locator('[data-testid="import-errors"]')
        errors_section.wait_for(timeout=5000)
        assert "Missing required field" in errors_section.text_content()

    def test_import_handles_network_error(self, page):
        """A failed request surfaces an error instead of hanging."""
        _open_paste_step(page)
        page.locator('[data-testid="raw-json-input"]').fill(
            json.dumps({"risks": [{"title": "Risk"}]})
        )
        page.route("**/api/import/json", lambda route: route.abort())
        page.locator('[data-testid="import-submit-btn"]').click()
        error = page.locator('[data-testid="import-error"]')
        error.wait_for(timeout=5000)
        assert error.is_visible()

    def test_copy_copilot_prompt_shows_toast(self, page):
        """Copy button copies the prompt and confirms with a toast."""
        _open_modal(page)
        page.wait_for_selector('[data-testid="copy-prompt-btn"]')

        prompt_text = page.locator('[data-testid="copilot-prompt-text"]').text_content()
        assert prompt_text.startswith("# Aufgabe")

        page.click('[data-testid="copy-prompt-btn"]')
        toast = page.locator(".toast")
        toast.wait_for(state="visible", timeout=3000)
        assert "copied" in toast.text_content().lower()

    def test_import_multiple_times(self, page):
        """Several imports in a row without reloading the page."""
        for i in range(3):
            _open_paste_step(page)
            _submit(page, {"risks": [{"title": f"Repeat Risk {i}"}]})
            page.locator("text=Successfully imported").wait_for(timeout=5000)
            # The dialog stays open by design, so close it before the next round.
            page.keyboard.press("Escape")
            page.wait_for_selector('[data-testid="json-import-modal"]',
                                   state="detached", timeout=3000)

    def test_prompt_picker_offers_every_tool(self, page):
        """Step 1 offers one prompt per screen, each loading its own schema."""
        _open_modal(page)
        for key, schema in (
            ("wbs", "hermes.wbs/v1"),
            ("timeline", "hermes.timeline/v1"),
            ("risks", "hermes.risks/v1"),
            ("pendenzen", "hermes.pendenzen/v1"),
            ("full", "hermes.project_state/v1"),
        ):
            page.locator(f'[data-testid="prompt-kind-{key}"]').click()
            page.wait_for_timeout(400)
            text = page.locator('[data-testid="copilot-prompt-text"]').text_content()
            assert f'"schema": "{schema}"' in text, key
