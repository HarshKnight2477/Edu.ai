"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  conversations: [],
  currentId: null,
  status: null,
  generating: false,
};

// --------------------------------------------------------------- helpers ----

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: options.body ? { "Content-Type": "application/json" } : {},
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join(", ") : body.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return response.status === 204 ? null : response.json();
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function scrollToBottom(force = false) {
  const box = $("messages");
  const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
  if (force || nearBottom) box.scrollTop = box.scrollHeight;
}

// ---------------------------------------------------------------- status ----

let statusTimer = null;

async function refreshStatus() {
  try {
    state.status = await api("/api/status");
  } catch {
    state.status = { state: "error", error: "EduLite's server is not responding." };
  }
  renderStatus();
  clearTimeout(statusTimer);
  // Poll quickly while the model loads, slowly otherwise (memory readout).
  statusTimer = setTimeout(refreshStatus, state.status.state === "loading" ? 1000 : 15000);
}

function renderStatus() {
  const s = state.status;
  const box = $("status");
  box.className = "status " + (s.state || "");
  let text;
  if (s.state === "ready") {
    const ram = s.ram_mb ? ` · ${(s.ram_mb / 1024).toFixed(1)} GB RAM` : "";
    text = `${s.model.name}${ram}`;
  } else if (s.state === "loading") {
    text = `Loading ${s.model ? s.model.name : "model"}…`;
  } else if (s.state === "error") {
    text = "Model error";
    box.title = s.error || "";
  } else {
    text = s.state || "Unknown";
  }
  $("status-text").textContent = text;
  if (s.modes && $("mode").options.length <= 1) {
    $("mode").replaceChildren(...Object.entries(s.modes).map(([value, label]) => {
      const option = el("option", "", label);
      option.value = value;
      return option;
    }));
  }
  updateComposer();
}

function modeLabel(mode) {
  return (state.status && state.status.modes && state.status.modes[mode]) || mode;
}

function chipsNode(mode, sources, auto) {
  const chips = el("div", "chips");
  if (mode) {
    const chip = el("span", "chip mode-chip", modeLabel(mode) + (auto ? " (auto)" : ""));
    chip.title = "How EduLite chose to answer. Change it with the picker next to the message box.";
    chips.appendChild(chip);
  }
  for (const source of sources || []) {
    const chip = el("span", "chip", "📘 " + source);
    chip.title = "From EduLite's course notes";
    chips.appendChild(chip);
  }
  return chips;
}

function updateComposer() {
  const ready = state.status && state.status.state === "ready";
  $("send").hidden = state.generating;
  $("stop").hidden = !state.generating;
  $("send").disabled = !ready || state.generating;
  $("input").placeholder = ready ? "Ask EduLite a question…"
    : state.status && state.status.state === "error" ? "The model could not start. Open Settings or check the terminal."
    : "Loading the model…";
}

// --------------------------------------------------------- conversations ----

async function loadConversations() {
  state.conversations = await api("/api/conversations");
  renderConversationList();
}

function renderConversationList() {
  const list = $("conversations");
  list.replaceChildren();
  if (!state.conversations.length) {
    list.appendChild(el("li", "empty", "No chats yet"));
    return;
  }
  for (const conversation of state.conversations) {
    const li = el("li", conversation.id === state.currentId ? "active" : "");
    const open = el("button", "open", conversation.title);
    open.type = "button";
    open.title = conversation.title;
    open.addEventListener("click", () => openConversation(conversation.id));
    const actions = el("span", "actions");
    const rename = el("button", "", "✎");
    rename.type = "button";
    rename.title = "Rename";
    rename.setAttribute("aria-label", `Rename ${conversation.title}`);
    rename.addEventListener("click", () => renameConversation(conversation));
    const remove = el("button", "", "🗑");
    remove.type = "button";
    remove.title = "Delete";
    remove.setAttribute("aria-label", `Delete ${conversation.title}`);
    remove.addEventListener("click", () => deleteConversation(conversation));
    actions.append(rename, remove);
    li.append(open, actions);
    list.appendChild(li);
  }
}

async function openConversation(id) {
  if (state.generating) return;
  const conversation = await api(`/api/conversations/${id}`);
  state.currentId = id;
  $("chat-title").textContent = conversation.title;
  renderMessages(conversation.messages);
  renderConversationList();
  $("sidebar").classList.remove("open");
  $("input").focus();
}

function newChat() {
  if (state.generating) return;
  state.currentId = null;
  $("chat-title").textContent = "New chat";
  renderMessages([]);
  renderConversationList();
  $("sidebar").classList.remove("open");
  $("input").focus();
}

async function renameConversation(conversation) {
  const title = prompt("Rename chat", conversation.title);
  if (!title || !title.trim()) return;
  await api(`/api/conversations/${conversation.id}`, { method: "PATCH", body: JSON.stringify({ title: title.trim() }) });
  if (conversation.id === state.currentId) $("chat-title").textContent = title.trim();
  await loadConversations();
}

async function deleteConversation(conversation) {
  if (!confirm(`Delete "${conversation.title}"? This can't be undone.`)) return;
  await api(`/api/conversations/${conversation.id}`, { method: "DELETE" });
  if (conversation.id === state.currentId) newChat();
  await loadConversations();
}

// -------------------------------------------------------------- messages ----

function renderMessages(messages) {
  const box = $("messages");
  box.replaceChildren();
  if (!messages.length) {
    box.appendChild($("welcome-template").content.cloneNode(true));
    bindSuggestions();
    return;
  }
  for (const message of messages) box.appendChild(messageNode(message));
  scrollToBottom(true);
}

function messageNode(message) {
  const wrap = el("div", `msg ${message.role}`);
  if (message.role === "assistant") {
    wrap.appendChild(el("div", "who", "EduLite"));
    const stats = message.stats || {};
    if (stats.mode || (stats.sources && stats.sources.length)) wrap.appendChild(chipsNode(stats.mode, stats.sources));
  }
  const bubble = el("div", "bubble");
  if (message.role === "assistant") bubble.appendChild(EduMarkdown.render(message.content, document, window.hljs));
  else bubble.textContent = message.content;
  wrap.appendChild(bubble);
  if (message.role === "assistant") wrap.appendChild(metaNode(message));
  return wrap;
}

function metaNode(message) {
  const meta = el("div", "meta");
  const stats = message.stats || {};
  if (message.stopped) meta.appendChild(el("span", "badge warn", "stopped"));
  if (stats.finish_reason === "length") meta.appendChild(el("span", "badge warn", "cut off: ask it to continue"));
  if (stats.forgotten_exchanges) meta.appendChild(el("span", "badge", `forgot ${stats.forgotten_exchanges} older exchange(s) to fit`));
  const parts = [];
  if (message.model) parts.push(message.model);
  if (stats.seconds) parts.push(`${stats.seconds} s`);
  if (stats.tokens_per_second) parts.push(`${stats.tokens_per_second.toFixed(1)} tok/s`);
  if (parts.length) meta.appendChild(el("span", "", parts.join(" · ")));
  return meta;
}

function errorNode(text) {
  const wrap = el("div", "msg error");
  wrap.appendChild(el("div", "bubble", text));
  return wrap;
}

// ------------------------------------------------------------- streaming ----

async function* readEvents(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      let event = "message";
      let data = "";
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (data) yield { event, data: JSON.parse(data) };
    }
  }
}

async function send(text) {
  if (state.generating || !text.trim()) return;
  state.generating = true;
  updateComposer();
  const box = $("messages");
  box.querySelector(".welcome")?.remove();

  let assistantWrap = null;
  try {
    if (state.currentId === null) {
      const conversation = await api("/api/conversations", { method: "POST" });
      state.currentId = conversation.id;
    }
    const response = await fetch(`/api/conversations/${state.currentId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: text, mode: $("mode").value }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (${response.status})`);
    }

    let answer = "";
    let pending = false;
    let bubble = null;
    const paint = () => {
      pending = false;
      bubble.replaceChildren(EduMarkdown.render(answer, document, window.hljs));
      scrollToBottom();
    };

    for await (const { event, data } of readEvents(response)) {
      if (event === "user") {
        box.appendChild(messageNode(data));
        assistantWrap = el("div", "msg assistant");
        assistantWrap.appendChild(el("div", "who", "EduLite"));
        bubble = el("div", "bubble cursor");
        assistantWrap.appendChild(bubble);
        box.appendChild(assistantWrap);
        scrollToBottom(true);
      } else if (event === "meta") {
        if (assistantWrap) assistantWrap.insertBefore(chipsNode(data.mode, data.sources, data.auto), bubble);
      } else if (event === "token") {
        answer += data.text;
        // Re-render at most once per frame: smooth even for fast models.
        if (!pending) { pending = true; requestAnimationFrame(paint); }
      } else if (event === "done") {
        assistantWrap.replaceWith(messageNode(data));
        assistantWrap = null;
        scrollToBottom();
      } else if (event === "error") {
        if (assistantWrap) assistantWrap.remove();
        if (data.removed_message_id) box.lastElementChild?.remove();
        box.appendChild(errorNode(data.message));
        assistantWrap = null;
      }
    }
  } catch (error) {
    if (assistantWrap) assistantWrap.remove();
    box.appendChild(errorNode(error.message));
  } finally {
    state.generating = false;
    updateComposer();
    await loadConversations();
    const current = state.conversations.find((c) => c.id === state.currentId);
    if (current) $("chat-title").textContent = current.title;
    scrollToBottom();
  }
}

// -------------------------------------------------------------- settings ----

function openSettings() {
  const s = state.status;
  if (!s || !s.settings) return;
  const select = $("set-model");
  select.replaceChildren();
  for (const model of s.models) {
    const option = el("option", "", `${model.name} (${model.quantization}, ~${model.ram_gb} GB RAM)` +
      (model.installed ? "" : " — not installed"));
    option.value = model.key;
    option.disabled = !model.installed;
    select.appendChild(option);
  }
  select.value = s.settings.model;
  $("set-level").value = s.settings.level;
  $("set-notes").checked = s.settings.use_notes;
  $("set-context").value = String(s.settings.context_tokens);
  $("set-max").value = s.settings.max_tokens;
  $("set-threads").value = s.settings.threads;
  $("set-temp").value = s.settings.temperature;
  $("temp-out").textContent = Number(s.settings.temperature).toFixed(1);
  $("settings-error").textContent = "";
  updateModelNote();
  $("settings-dialog").showModal();
}

function updateModelNote() {
  const notes = {
    default: "Balanced: good explanations and debugging. Recommended for 8 GB PCs.",
    lite: "Fastest and lightest. Good for concepts; weaker at writing and fixing code.",
    quality: "Best answers, but slower and needs more memory.",
  };
  $("model-note").textContent = notes[$("set-model").value] || "";
}

async function saveSettings(event) {
  event.preventDefault();
  const body = {
    model: $("set-model").value,
    context_tokens: Number($("set-context").value),
    max_tokens: Number($("set-max").value),
    threads: Number($("set-threads").value),
    temperature: Number($("set-temp").value),
    level: $("set-level").value,
    use_notes: $("set-notes").checked,
  };
  const save = $("settings-save");
  save.disabled = true;
  save.textContent = "Applying…";
  $("settings-error").textContent = "";
  try {
    state.status = await api("/api/settings", { method: "PUT", body: JSON.stringify(body) });
    renderStatus();
    $("settings-dialog").close();
  } catch (error) {
    $("settings-error").textContent = error.message;
  } finally {
    save.disabled = false;
    save.textContent = "Save";
    refreshStatus();
  }
}

// ----------------------------------------------------------------- wiring ----

function bindSuggestions() {
  document.querySelectorAll(".suggestion").forEach((button) =>
    button.addEventListener("click", () => send(button.textContent)));
}

function autosize() {
  const input = $("input");
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 220) + "px";
}

function init() {
  // Keep a pristine copy of the welcome screen for new chats.
  const template = document.createElement("template");
  template.id = "welcome-template";
  template.content.appendChild($("welcome").cloneNode(true));
  document.body.appendChild(template);
  bindSuggestions();

  $("composer").addEventListener("submit", (event) => {
    event.preventDefault();
    const text = $("input").value;
    if (!text.trim() || $("send").disabled) return;
    $("input").value = "";
    autosize();
    send(text);
  });
  $("input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      $("composer").requestSubmit();
    }
  });
  $("input").addEventListener("input", autosize);
  $("stop").addEventListener("click", () => api("/api/stop", { method: "POST" }).catch(() => {}));
  $("new-chat").addEventListener("click", newChat);
  $("toggle-sidebar").addEventListener("click", () => $("sidebar").classList.toggle("open"));
  $("open-settings").addEventListener("click", openSettings);
  $("settings-cancel").addEventListener("click", () => $("settings-dialog").close());
  $("settings-form").addEventListener("submit", saveSettings);
  $("set-model").addEventListener("change", updateModelNote);
  $("set-temp").addEventListener("input", () => { $("temp-out").textContent = Number($("set-temp").value).toFixed(1); });

  // Copy buttons on code blocks (delegated, works for streamed content too).
  $("messages").addEventListener("click", async (event) => {
    const button = event.target.closest("button.copy");
    if (!button) return;
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      button.textContent = "Copied";
    } catch {
      button.textContent = "Copy failed";
    }
    setTimeout(() => { button.textContent = "Copy"; }, 1500);
  });

  refreshStatus();
  loadConversations().then(() => {
    if (state.conversations.length) openConversation(state.conversations[0].id);
  });
}

init();
