// SecureAssist chat UI (PREDEFINED). History lives only in this page session.
// All text is inserted with textContent, so model output can never run as HTML/JS.
(function () {
  const form = document.getElementById("chat-form");
  const input = document.getElementById("message");
  const sendBtn = document.getElementById("send");
  const historyEl = document.getElementById("history");
  const statusEl = document.getElementById("status");

  function addMessage(kind, text, badges) {
    const wrap = document.createElement("div");
    wrap.className = "msg " + kind;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    wrap.appendChild(bubble);
    if (badges && badges.length) {
      const row = document.createElement("div");
      row.className = "badges";
      badges.forEach(function (b) {
        const span = document.createElement("span");
        span.className = "badge " + (b.cls || "");
        span.textContent = b.text;
        row.appendChild(span);
      });
      wrap.appendChild(row);
    }
    historyEl.appendChild(wrap);
    historyEl.scrollTop = historyEl.scrollHeight;
  }

  function setLoading(on) {
    sendBtn.disabled = on;
    input.disabled = on;
    if (on) {
      statusEl.innerHTML = '<span class="spinner"></span>SecureAssist is thinking… (phi3:mini on CPU can take up to a minute)';
      statusEl.classList.remove("hidden");
    } else {
      statusEl.classList.add("hidden");
    }
  }

  function badgesFor(body) {
    const badges = [];
    (body.tools_used || []).forEach(function (t) {
      badges.push({ text: "🔧 MCP tool: " + t.name + " (" + t.outcome + ")", cls: "tool" });
    });
    if (body.route) badges.push({ text: "route: " + body.route });
    if (body.degraded) badges.push({ text: "degraded: model unavailable", cls: "warn" });
    if (body.duration_ms !== undefined) badges.push({ text: body.duration_ms + " ms" });
    if (body.trace_id) badges.push({ text: "trace " + body.trace_id.slice(0, 8) });
    if (body.monitoring) badges.push({ text: "monitoring: " + body.monitoring });
    return badges;
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const message = input.value.trim();
    if (!message) {
      addMessage("blocked", "Please type a question first.");
      return;
    }
    addMessage("user", message);
    input.value = "";
    setLoading(true);
    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message }),
      });
      let body = {};
      try { body = await resp.json(); } catch (e) { body = {}; }
      if (body.blocked) {
        addMessage("blocked", "⛔ Blocked by guardrails: " + body.guardrail.reason,
          [{ text: "guardrail: " + body.guardrail.category, cls: "warn" }].concat(badgesFor(body)));
      } else if (resp.ok && body.answer) {
        addMessage("bot", body.answer, badgesFor(body));
      } else {
        const err = body.error || { message: "Unexpected error (HTTP " + resp.status + ")." };
        const extra = err.dependency ? [{ text: "failed dependency: " + err.dependency, cls: "warn" }] : [];
        addMessage("error", "⚠️ " + err.message, extra.concat(badgesFor(body)));
      }
    } catch (e) {
      addMessage("error", "⚠️ Could not reach SecureAssist. Check your connection and try again.");
    } finally {
      setLoading(false);
      input.focus();
    }
  });
})();
