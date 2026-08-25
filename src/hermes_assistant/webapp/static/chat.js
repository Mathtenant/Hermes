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
  };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function render(root) {
    var msgs = state.messages
      .map(function (m) {
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

    var bodyInner = state.isOpen
      ? '<div class="chat-messages" aria-live="polite" aria-atomic="false" aria-label="Chat messages">' +
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
    root.innerHTML =
      '<div id="chat-widget" class="panel ' +
      (state.isOpen ? "is-open" : "is-collapsed") +
      '">' +
      '<div class="chat-header">' +
      '<h3 class="chat-title"><span class="chat-dot" aria-hidden="true"></span>Hermes Chat</h3>' +
      '<button class="chat-toggle" data-collapse-target="chat-widget-body" aria-expanded="' +
      String(state.isOpen) +
      '" aria-label="' +
      (state.isOpen ? "Collapse chat" : "Expand chat") +
      '">' +
      (state.isOpen ? "−" : "+") +
      "</button>" +
      "</div>" +
      body +
      "</div>";

    wire(root);
  }

  function wire(root) {
    var toggle = root.querySelector(".chat-toggle");
    if (toggle) {
      toggle.onclick = function () {
        state.isOpen = !state.isOpen;
        // Persist so a page reload keeps the panel collapsed/expanded.
        writeCollapsed(!state.isOpen);
        render(root);
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
