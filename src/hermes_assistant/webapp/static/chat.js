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

  // ── Tab title flash ──────────────────────────────────────────────────────
  // Local inference can take a while, so people tab away mid-question. When a
  // reply lands while the tab is hidden, alternate the tab title with a notice
  // until they come back. Nothing is shown while the tab is visible — the
  // streamed bubble is already the signal there.
  var FLASH_INTERVAL_MS = 1200;
  var baseTitle = null; // real page title, captured when a flash cycle starts
  var flashTimer = null;
  var unreadReplies = 0;

  function noticeTitle() {
    var count = unreadReplies > 1 ? "(" + unreadReplies + ") " : "";
    var plural = unreadReplies > 1 ? "replies" : "reply";
    return count + "💬 Hermes " + plural + " ready";
  }

  function startTitleFlash() {
    if (flashTimer) {
      // Already flashing: refresh the notice so the count stays current.
      document.title = noticeTitle();
      return;
    }
    // Safe to read the live title: the guard above means we are not flashing,
    // so document.title is the page's own, not a notice we wrote.
    baseTitle = document.title;
    var showingNotice = true;
    document.title = noticeTitle();
    flashTimer = setInterval(function () {
      showingNotice = !showingNotice;
      document.title = showingNotice ? noticeTitle() : baseTitle;
    }, FLASH_INTERVAL_MS);
  }

  function stopTitleFlash() {
    if (flashTimer) {
      clearInterval(flashTimer);
      flashTimer = null;
    }
    if (baseTitle !== null) {
      document.title = baseTitle;
      baseTitle = null;
    }
    unreadReplies = 0;
  }

  /** Called when a turn finishes (reply or error) — the inference is done. */
  function notifyReplyReady() {
    if (!document.hidden) return; // they are watching; the bubble suffices
    unreadReplies += 1;
    startTitleFlash();
  }

  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) stopTitleFlash();
    });
    // Covers the case where the tab was never hidden but the window lost focus
    // (separate monitor, other app) and is clicked back into.
    window.addEventListener("focus", stopTitleFlash);
  }

  // ── HTML builders (shared by the full rebuild and the incremental patch) ──
  function messagesHtml() {
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
                  esc(s) + '">' + esc(s) + "</button>"
                );
              })
              .join("") +
            "</div>";
        }
        return (
          '<div class="chat-row' + (mine ? " mine" : "") + '">' +
          '<div class="chat-bubble ' + (mine ? "mine" : "theirs") + '">' +
          esc(m.content) +
          "</div>" + suggestions + "</div>"
        );
      })
      .join("");
    return msgs ||
      '<div class="chat-empty">Ask Hermes about risks, pendenzen or the plan.</div>';
  }

  function typingHtml() {
    return state.isLoading
      ? '<div class="chat-typing">Assistant is typing…</div>'
      : "";
  }

  function modelBarHtml() {
    var options = state.models
      .map(function (m) {
        return (
          '<option value="' + esc(m) + '"' +
          (m === state.currentModel ? " selected" : "") + ">" + esc(m) + "</option>"
        );
      })
      .join("");
    if (!state.models.length && state.currentModel) {
      options =
        '<option value="' + esc(state.currentModel) + '" selected>' +
        esc(state.currentModel) + "</option>";
    }
    return (
      '<div class="chat-modelbar">' +
      '<label for="chat-model" class="sr-only">Chat model</label>' +
      '<select id="chat-model" class="chat-model-select" data-testid="chat-model-select"' +
      (state.models.length ? "" : " disabled") + ">" +
      (options || '<option value="">No models found</option>') +
      "</select>" +
      (state.modelError
        ? '<span class="chat-model-error" data-testid="chat-model-error">' +
          esc(state.modelError) + "</span>"
        : "") +
      "</div>"
    );
  }

  function renderShell(root) {
    var bodyInner = state.isOpen
      ? modelBarHtml() +
        '<div class="chat-messages" aria-live="polite" aria-atomic="false" aria-label="Chat messages">' +
        messagesHtml() + typingHtml() +
        "</div>" +
        '<div class="chat-composer">' +
        '<label for="chat-input" class="sr-only">Message</label>' +
        '<input id="chat-input" class="chat-input" aria-label="Chat message input" placeholder="Ask Hermes…" />' +
        '<button class="chat-send" aria-label="Send message">Send</button>' +
        "</div>"
      : "";

    var bodyStyle = state.isOpen
      ? "flex:1;display:flex;flex-direction:column;overflow:hidden;"
      : "display:none;";
    var body =
      '<div id="chat-widget-body" class="panel-body" style="' + bodyStyle + '">' +
      bodyInner + "</div>";

    root.innerHTML =
      '<div id="chat-widget" class="panel ' +
      (state.isOpen ? "is-open" : "is-collapsed") + '">' +
      '<div class="chat-header" role="button" tabindex="0" data-testid="chat-header"' +
      ' aria-controls="chat-widget-body" aria-expanded="' + String(state.isOpen) +
      '" aria-label="' + (state.isOpen ? "Collapse chat" : "Expand chat") + '">' +
      '<h3 class="chat-title"><span class="chat-dot" aria-hidden="true"></span>Hermes Chat</h3>' +
      '<button class="chat-toggle" data-collapse-target="chat-widget-body" tabindex="-1"' +
      ' aria-hidden="true">' + (state.isOpen ? "−" : "+") + "</button>" +
      "</div>" + body + "</div>";

    wire(root);
  }

  /** Rebuild only the parts that change while the user may be typing.
   *
   * Replacing the whole subtree on every streamed token destroyed whatever
   * was in the composer — and worse, could swap the element out *during* a
   * keystroke or a programmatic fill, so the text landed on a node already
   * detached from the document and the message was silently never sent.
   * Preserving the value across the swap could not fix that: the race is with
   * the write itself, not with the value.
   *
   * The composer and header are therefore built once and left alone; only the
   * message list and the model bar are refreshed.
   */
  function patch(root) {
    var messages = root.querySelector(".chat-messages");
    if (messages) messages.innerHTML = messagesHtml() + typingHtml();

    var bar = root.querySelector(".chat-modelbar");
    if (bar) {
      var select = bar.querySelector(".chat-model-select");
      // Leave an open dropdown alone; rewriting it would close it mid-choice.
      if (select && document.activeElement !== select) {
        bar.outerHTML = modelBarHtml();
      } else if (!select) {
        bar.outerHTML = modelBarHtml();
      }
    }
  }

  function render(root) {
    // A structural change (collapsing/expanding) genuinely needs a rebuild,
    // and only happens on an explicit click — never mid-typing.
    var widget = root.querySelector("#chat-widget");
    var openNow = widget && widget.classList.contains("is-open");
    if (!widget || openNow !== state.isOpen) {
      renderShell(root);
      return;
    }
    patch(root);
    var list = root.querySelector(".chat-messages");
    if (list) list.scrollTop = list.scrollHeight;
  }

  // Delegated listeners are attached once to the mount point, which survives
  // every render, instead of being re-bound to fresh nodes on each one.
  // Per-render binding loses events that arrive while the subtree is being
  // replaced: an async render (the model list resolving, a stream finishing)
  // landing between typing and clicking dropped the message entirely.
  function wireOnce(root) {
    if (root._hermesWired) return;
    root._hermesWired = true;

    function liveInputValue() {
      var el = root.querySelector(".chat-input");
      return el ? el.value : "";
    }

    root.addEventListener("click", function (e) {
      var suggestion = e.target.closest && e.target.closest(".chat-suggestion");
      if (suggestion) {
        sendMessage(root, suggestion.getAttribute("data-suggestion"));
        return;
      }
      if (e.target.closest && e.target.closest(".chat-send")) {
        sendMessage(root, liveInputValue());
        return;
      }
      // The model picker sits below the header; interacting with it must not
      // bubble up into the collapse toggle.
      if (e.target.closest && e.target.closest(".chat-model-select")) return;
      if (e.target.closest && e.target.closest(".chat-header")) {
        toggleOpen(root);
      }
    });

    root.addEventListener("keydown", function (e) {
      if (e.target.closest && e.target.closest(".chat-input")) {
        if (e.key === "Enter") sendMessage(root, e.target.value);
        return;
      }
      if (e.target.closest && e.target.closest(".chat-header")) {
        if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
          e.preventDefault(); // Space would otherwise scroll the page
          toggleOpen(root);
        }
      }
    });

    root.addEventListener("change", function (e) {
      if (e.target.closest && e.target.closest(".chat-model-select")) {
        selectModel(root, e.target.value);
      }
    });
  }

  function toggleOpen(root) {
    state.isOpen = !state.isOpen;
    // Persist so a page reload keeps the panel collapsed/expanded.
    writeCollapsed(!state.isOpen);
    render(root);
    if (state.isOpen) loadModels(root);
  }

  function wire(root) {
    // Behaviour lives in the delegated listeners installed by wireOnce(); the
    // only per-render work left is scrolling to the newest message.
    wireOnce(root);
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
        // Name the likely cause rather than surfacing a bare "Failed to fetch":
        // the usual reason is the local server being down, which the user can
        // act on. The raw message is kept for anything less obvious.
        var detail = String((err && err.message) || err);
        var unreachable = /failed to fetch|networkerror|load failed/i.test(detail);
        state.messages[assistantIdx].content = unreachable
          ? "Error: the Hermes server is unreachable — is it still running? (" +
            detail + ")"
          : "Error: " + detail;
      })
      .then(function () {
        state.isLoading = false;
        render(root);
        // Fires for both a completed reply and an error — either way the wait
        // is over, which is what someone who tabbed away wants to know.
        notifyReplyReady();
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
