// Hermes chat widget — self-contained vanilla JS (no build step, no framework
// dependency). Exposes window.ChatWidget with a mount(el) method and auto-mounts
// into #chat-app on DOMContentLoaded. Deliberately framework-free: it lives
// outside the Vue root (#app) so a dashboard re-render never interrupts an
// in-flight streamed reply. Presentation comes from style.css so it themes with
// the rest of the dashboard.

(function () {
  "use strict";

  var COLLAPSE_KEY = "panel-collapsed-chat-widget-body";

  function readCollapsed() {
    try {
      return sessionStorage.getItem(COLLAPSE_KEY) === "true";
    } catch (e) {
      return false;
    }
  }

  function writeCollapsed(collapsed) {
    try {
      sessionStorage.setItem(COLLAPSE_KEY, String(collapsed));
    } catch (e) {
      /* sessionStorage unavailable (private mode) — ignore. */
    }
  }

  var state = {
    // Restore collapsed state from a prior visit so a reload preserves it.
    isOpen: !readCollapsed(),
    isLoading: false,
    session: null,
    project: "default",
    messages: [],
    // Model picker: populated from GET /api/chat/models on first expand.
    models: [],
    currentModel: "",
    modelsLoaded: false,
    modelError: "",
  };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ── Model picker ─────────────────────────────────────────────────────────
  // Loaded lazily (first expand) so a collapsed widget costs no request.
  function loadModels(root) {
    if (state.modelsLoaded) return;
    state.modelsLoaded = true;
    fetch("/api/chat/models")
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (data) {
        if (!data) return;
        state.models = data.models || [];
        state.currentModel = data.current || "";
        state.modelError = data.available
          ? ""
          : "Ollama unreachable — start it with `ollama serve`";
        render(root);
      })
      .catch(function () {
        state.modelError = "Could not load the model list";
        render(root);
      });
  }

  function selectModel(root, model) {
    if (!model || model === state.currentModel) return;
    var previous = state.currentModel;
    state.currentModel = model;
    state.modelError = "";
    render(root);

    fetch("/api/chat/model", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: model }),
    })
      .then(function (r) {
        return r.json().then(function (body) {
          return { ok: r.ok, body: body };
        });
      })
      .then(function (res) {
        if (res.ok) {
          state.currentModel = res.body.current || model;
          pushSystemNote("Model switched to " + state.currentModel);
        } else {
          // Roll back so the dropdown never shows a model the server rejected.
          state.currentModel = previous;
          state.modelError =
            typeof res.body.detail === "string"
              ? res.body.detail
              : "Could not switch model";
        }
        render(root);
      })
      .catch(function (err) {
        state.currentModel = previous;
        state.modelError = String(err.message || err);
        render(root);
      });
  }

  function pushSystemNote(text) {
    state.messages.push({ role: "system", content: text });
  }

  function render(root) {
    var msgs = state.messages
      .map(function (m) {
        if (m.role === "system") {
          return '<div class="chat-note">' + esc(m.content) + "</div>";
        }
        var mine = m.role === "user";
        var suggestions = "";
        if (m.suggestions && m.suggestions.length) {
          suggestions =
            '<div class="chat-suggestions">' +
            m.suggestions
              .map(function (s) {
                return (
                  '<button class="chat-suggestion" data-suggestion="' +
                  esc(s) +
                  '">' +
                  esc(s) +
                  "</button>"
                );
              })
              .join("") +
            "</div>";
        }
        return (
          '<div class="chat-row' + (mine ? " mine" : "") + '">' +
          '<div class="chat-bubble ' + (mine ? "mine" : "theirs") + '">' +
          esc(m.content) +
          "</div>" +
          suggestions +
          "</div>"
        );
      })
      .join("");

    if (!msgs) {
      msgs =
        '<div class="chat-empty">Ask Hermes about risks, pendenzen or the plan.</div>';
    }

    var typing = state.isLoading
      ? '<div class="chat-typing">Assistant is typing…</div>'
      : "";

    // Model picker row. Rendered even before the list arrives so the widget
    // does not visibly reflow once /api/chat/models responds.
    var options = state.models
      .map(function (m) {
        return (
          '<option value="' +
          esc(m) +
          '"' +
          (m === state.currentModel ? " selected" : "") +
          ">" +
          esc(m) +
          "</option>"
        );
      })
      .join("");
    if (!state.models.length && state.currentModel) {
      options =
        '<option value="' + esc(state.currentModel) + '" selected>' +
        esc(state.currentModel) +
        "</option>";
    }
    var modelBar =
      '<div class="chat-modelbar">' +
      '<label for="chat-model" class="sr-only">Chat model</label>' +
      '<select id="chat-model" class="chat-model-select" data-testid="chat-model-select"' +
      (state.models.length ? "" : " disabled") +
      ">" +
      (options || '<option value="">No models found</option>') +
      "</select>" +
      (state.modelError
        ? '<span class="chat-model-error" data-testid="chat-model-error">' +
          esc(state.modelError) +
          "</span>"
        : "") +
      "</div>";

    var bodyInner = state.isOpen
      ? modelBar +
        '<div class="chat-messages" aria-live="polite" aria-atomic="false" aria-label="Chat messages">' +
        msgs +
        typing +
        "</div>" +
        '<div class="chat-composer">' +
        '<label for="chat-input" class="sr-only">Message</label>' +
        '<input id="chat-input" class="chat-input" aria-label="Chat message input" placeholder="Ask Hermes…" />' +
        '<button class="chat-send" aria-label="Send message">Send</button>' +
        "</div>"
      : "";

    // The body is always a distinctly-identified panel so collapse state is
    // addressable (#chat-widget-body). When collapsed it renders empty (no
    // child input), which both hides the panel and drops interactive controls.
    var bodyStyle = state.isOpen
      ? "flex:1;display:flex;flex-direction:column;overflow:hidden;"
      : "display:none;";
    var body =
      '<div id="chat-widget-body" class="panel-body" style="' +
      bodyStyle +
      '">' +
      bodyInner +
      "</div>";

    // When collapsed the container shrinks to just the header bar; `is-open`
    // gives the expanded panel its full canvas (see style.css).
    // render() replaces the whole subtree, so anything the user has typed (and
    // where their caret/focus was) would be lost. That matters because renders
    // are not only user-driven: the model list arriving, or a streamed token,
    // re-renders asynchronously and would otherwise wipe a half-typed message
    // mid-keystroke. Carry the composer state across the swap.
    var previousInput = root.querySelector(".chat-input");
    var draft = previousInput ? previousInput.value : "";
    var caret = previousInput ? previousInput.selectionStart : null;
    var hadFocus = previousInput && document.activeElement === previousInput;

    root.innerHTML =
      '<div id="chat-widget" class="panel ' +
      (state.isOpen ? "is-open" : "is-collapsed") +
      '">' +
      // The whole bar is the toggle — clicking anywhere on it (or pressing
      // Enter/Space while it is focused) expands/collapses the panel. The
      // +/- button stays for affordance and screen-reader labelling, but is
      // no longer the only hit target.
      '<div class="chat-header" role="button" tabindex="0" data-testid="chat-header"' +
      ' aria-controls="chat-widget-body" aria-expanded="' +
      String(state.isOpen) +
      '" aria-label="' +
      (state.isOpen ? "Collapse chat" : "Expand chat") +
      '">' +
      '<h3 class="chat-title"><span class="chat-dot" aria-hidden="true"></span>Hermes Chat</h3>' +
      '<button class="chat-toggle" data-collapse-target="chat-widget-body" tabindex="-1"' +
      ' aria-hidden="true">' +
      (state.isOpen ? "−" : "+") +
      "</button>" +
      "</div>" +
      body +
      "</div>";

    var nextInput = root.querySelector(".chat-input");
    if (nextInput && draft) {
      nextInput.value = draft;
      if (hadFocus) {
        nextInput.focus();
        if (caret !== null) {
          try {
            nextInput.setSelectionRange(caret, caret);
          } catch (e) {
            /* older browsers — restoring the text alone is enough */
          }
        }
      }
    }

    wire(root);
  }

  function wire(root) {
    function toggleOpen() {
      state.isOpen = !state.isOpen;
      // Persist so a page reload keeps the panel collapsed/expanded.
      writeCollapsed(!state.isOpen);
      render(root);
      if (state.isOpen) loadModels(root);
    }

    // Whole header bar toggles. The inner button has no own handler — the
    // click bubbles to the header, so a single listener covers both.
    var header = root.querySelector(".chat-header");
    if (header) {
      header.onclick = toggleOpen;
      header.onkeydown = function (e) {
        if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
          e.preventDefault(); // Space would otherwise scroll the page
          toggleOpen();
        }
      };
    }

    var modelSelect = root.querySelector(".chat-model-select");
    if (modelSelect) {
      modelSelect.onchange = function () {
        selectModel(root, this.value);
      };
      // The picker sits inside the header's sibling body, but guard anyway so
      // interacting with it can never collapse the panel.
      modelSelect.onclick = function (e) {
        e.stopPropagation();
      };
    }

    var input = root.querySelector(".chat-input");
    var send = root.querySelector(".chat-send");
    if (send && input) {
      send.onclick = function () {
        sendMessage(root, input.value);
      };
      input.onkeyup = function (e) {
        if (e.key === "Enter") sendMessage(root, input.value);
      };
    }
    var sugg = root.querySelectorAll(".chat-suggestion");
    for (var i = 0; i < sugg.length; i++) {
      sugg[i].onclick = function () {
        sendMessage(root, this.getAttribute("data-suggestion"));
      };
    }
    // Keep the message list scrolled to the newest message.
    var list = root.querySelector(".chat-messages");
    if (list) list.scrollTop = list.scrollHeight;
  }

  function sendMessage(root, text) {
    if (!text || !text.trim()) return;
    // Clear the live composer before rendering: render() preserves whatever is
    // in the field, so the sent text would otherwise stay behind.
    var composer = root.querySelector(".chat-input");
    if (composer) composer.value = "";
    state.messages.push({ role: "user", content: text });
    state.isLoading = true;
    // Placeholder assistant bubble updated token-by-token during streaming.
    var assistantIdx = state.messages.length;
    state.messages.push({ role: "assistant", content: "" });
    render(root);

    var accum = "";
    var sseBuffer = "";
    var currentEvent = "data";

    fetch("/api/chat/message/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        project_id: state.project,
        session_id: state.session,
      }),
    })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        var reader = r.body.getReader();
        var decoder = new TextDecoder();

        function pump() {
          return reader.read().then(function (result) {
            if (result.done) return;
            sseBuffer += decoder.decode(result.value, { stream: true });
            var lines = sseBuffer.split("\n");
            // Keep the last (possibly incomplete) line in the buffer.
            sseBuffer = lines.pop();

            for (var i = 0; i < lines.length; i++) {
              var line = lines[i];
              if (line.indexOf("event:") === 0) {
                currentEvent = line.slice(6).trim();
              } else if (line.indexOf("data:") === 0) {
                var raw = line.slice(5).trim();
                if (currentEvent === "data") {
                  try {
                    var chunk = JSON.parse(raw);
                    accum += chunk;
                    // Drop the typing indicator on the first token.
                    if (state.isLoading) state.isLoading = false;
                    state.messages[assistantIdx].content = accum;
                    render(root);
                  } catch (e) { /* skip malformed chunk */ }
                } else if (currentEvent === "done") {
                  try {
                    var done = JSON.parse(raw);
                    if (done.session_id) state.session = done.session_id;
                    state.messages[assistantIdx].suggestions = done.suggestions || [];
                  } catch (e) { /* ignore */ }
                } else if (currentEvent === "error") {
                  state.messages[assistantIdx].content = "Error: Internal error";
                }
              } else if (line.trim() === "") {
                currentEvent = "data"; // Reset event type on blank separator line.
              }
            }

            return pump();
          });
        }

        return pump();
      })
      .catch(function (err) {
        state.messages[assistantIdx].content = "Error: " + err.message;
      })
      .then(function () {
        state.isLoading = false;
        render(root);
      });
  }

  window.ChatWidget = {
    state: state,
    mount: function (el) {
      var root = typeof el === "string" ? document.querySelector(el) : el;
      if (!root) return;
      render(root);
      // Only fetch the model list when the panel starts expanded; a collapsed
      // widget stays free until the user opens it.
      if (state.isOpen) loadModels(root);
      return root;
    },
  };

  // Generic collapse for any *other* panel that opts in via
  // [data-collapse-target]. The chat widget re-renders itself, so its own
  // toggle (inside #chat-widget) is intentionally excluded here to avoid a
  // double toggle. Uses event delegation so panels injected later still work.
  function genericCollapse(e) {
    var btn = e.target.closest && e.target.closest("[data-collapse-target]");
    if (!btn) return;
    if (btn.closest("#chat-widget")) return; // handled by the widget itself
    var panel = document.getElementById(btn.dataset.collapseTarget);
    if (!panel) return;
    var isCollapsed = panel.classList.toggle("is-collapsed");
    btn.textContent = isCollapsed ? "+" : "−";
    btn.setAttribute("aria-expanded", String(!isCollapsed));
    try {
      sessionStorage.setItem(
        "panel-collapsed-" + btn.dataset.collapseTarget,
        String(isCollapsed)
      );
    } catch (err) {
      /* ignore */
    }
  }

  function restoreGenericPanels() {
    var btns = document.querySelectorAll("[data-collapse-target]");
    for (var i = 0; i < btns.length; i++) {
      var btn = btns[i];
      if (btn.closest("#chat-widget")) continue;
      var targetId = btn.dataset.collapseTarget;
      var panel = document.getElementById(targetId);
      var wasCollapsed =
        sessionStorage.getItem("panel-collapsed-" + targetId) === "true";
      if (wasCollapsed && panel) {
        panel.classList.add("is-collapsed");
        btn.textContent = "+";
        btn.setAttribute("aria-expanded", "false");
      }
    }
  }

  if (typeof document !== "undefined") {
    document.addEventListener("click", genericCollapse);
    document.addEventListener("DOMContentLoaded", function () {
      var mountEl = document.getElementById("chat-app");
      if (mountEl) window.ChatWidget.mount(mountEl);
      restoreGenericPanels();
    });
  }
})();
