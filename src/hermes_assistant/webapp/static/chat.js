// Hermes chat widget — self-contained vanilla JS (no build step, no framework
// dependency). Exposes window.ChatWidget with a mount(el) method and auto-mounts
// into #chat-app on DOMContentLoaded. Kept framework-free because index.html
// ships only a minimal non-reactive Vue stub.

(function () {
  "use strict";

  var state = {
    isOpen: true,
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
        var bubble = mine
          ? "align-self:flex-end;background:#3b82f6;color:#fff;"
          : "align-self:flex-start;background:#334155;color:#e2e8f0;";
        var suggestions = "";
        if (m.suggestions && m.suggestions.length) {
          suggestions =
            '<div class="chat-suggestions" style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-top:0.5rem;">' +
            m.suggestions
              .map(function (s) {
                return (
                  '<button class="chat-suggestion" data-suggestion="' +
                  esc(s) +
                  '" style="background:#10b981;color:#fff;padding:0.25rem 0.75rem;border:none;border-radius:4px;cursor:pointer;font-size:0.75rem;">' +
                  esc(s) +
                  "</button>"
                );
              })
              .join("") +
            "</div>";
        }
        return (
          '<div style="display:flex;flex-direction:column;gap:0.25rem;">' +
          '<div style="' +
          bubble +
          'padding:0.5rem 0.75rem;border-radius:6px;max-width:80%;">' +
          esc(m.content) +
          "</div>" +
          suggestions +
          "</div>"
        );
      })
      .join("");

    var typing = state.isLoading
      ? '<div class="chat-typing" style="align-self:flex-start;color:#94a3b8;font-size:0.875rem;">Assistant is typing...</div>'
      : "";

    var body = state.isOpen
      ? '<div class="chat-messages" style="flex:1;overflow-y:auto;padding:1rem;display:flex;flex-direction:column;gap:0.75rem;">' +
        msgs +
        typing +
        "</div>" +
        '<div style="border-top:1px solid #334155;padding:1rem;display:flex;gap:0.5rem;">' +
        '<input class="chat-input" placeholder="Ask Hermes..." style="flex:1;padding:0.5rem;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:4px;font-size:0.875rem;" />' +
        '<button class="chat-send" style="background:#10b981;color:#fff;padding:0.5rem 1rem;border:none;border-radius:4px;cursor:pointer;">Send</button>' +
        "</div>"
      : "";

    root.innerHTML =
      '<div id="chat-widget" style="position:fixed;bottom:20px;right:20px;width:400px;height:500px;border:1px solid #334155;border-radius:8px;background:#1e293b;display:flex;flex-direction:column;z-index:900;box-shadow:0 4px 12px rgba(0,0,0,0.3);">' +
      '<div style="background:#0f172a;padding:1rem;border-bottom:1px solid #334155;display:flex;justify-content:space-between;align-items:center;">' +
      '<h3 style="margin:0;color:#e2e8f0;font-size:1rem;">Hermes Chat</h3>' +
      '<button class="chat-toggle" style="background:none;border:none;color:#94a3b8;cursor:pointer;font-size:1.5rem;">' +
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
    render(root);

    fetch("/api/chat/message", {
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
        return r.json();
      })
      .then(function (data) {
        state.session = data.session_id;
        state.messages.push({
          role: "assistant",
          content: data.message.content,
          suggestions: data.suggestions || [],
        });
      })
      .catch(function (err) {
        state.messages.push({
          role: "assistant",
          content: "Error: " + err.message,
        });
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

  if (typeof document !== "undefined") {
    document.addEventListener("DOMContentLoaded", function () {
      var mountEl = document.getElementById("chat-app");
      if (mountEl) window.ChatWidget.mount(mountEl);
    });
  }
})();
