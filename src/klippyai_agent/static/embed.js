const body = document.body;
const apiBase = resolveApiBase(body.dataset.apiBase);
const messages = document.getElementById("messages");
const historyList = document.getElementById("history-list");
const providerBadge = document.getElementById("provider-badge");
const modelBadge = document.getElementById("model-badge");
const moonrakerBadge = document.getElementById("moonraker-badge");
const klipperBadge = document.getElementById("klipper-badge");
const sendButton = document.getElementById("send-button");
const newChatButton = document.getElementById("new-chat-button");
const composerStatus = document.getElementById("composer-status");
const messageInput = document.getElementById("message-input");
const template = document.getElementById("message-template");
const shellMenuToggle = document.getElementById("shell-menu-toggle");
const shellScrim = document.getElementById("shell-scrim");
const introMessage =
  document.querySelector("#messages .message.assistant .message-body")?.textContent?.trim() ||
  "Ask what failed or ask for config help.";
const STORAGE_KEY = "klippyai.embed.state.v2";
const LEGACY_STORAGE_KEY = "klippyai.embed.state.v1";

const timestampFormatter = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

let appState = {
  currentConversationId: null,
  conversations: [],
};
let isLoading = false;
let loadingConversationId = null;

function resolveApiBase(configuredApiBase) {
  const configured = String(configuredApiBase || "").trim();
  if (configured && configured !== "/api") {
    return configured.replace(/\/+$/, "");
  }

  const path = window.location.pathname.replace(/\/+$/, "");
  const inferredRoot = path.replace(/\/(?:embed|direct)$/i, "");
  if (inferredRoot && inferredRoot !== "/" && inferredRoot !== "/api") {
    return `${inferredRoot}/api`;
  }

  return configured || "/api";
}

function setText(element, text) {
  if (element) {
    element.textContent = text;
  }
}

function setDisabled(element, disabled) {
  if (element) {
    element.disabled = disabled;
  }
}

function setNavigationOpen(isOpen) {
  body.classList.toggle("nav-open", isOpen);
}

function initializeShellNavigation() {
  if (shellMenuToggle) {
    shellMenuToggle.addEventListener("click", () => {
      setNavigationOpen(!body.classList.contains("nav-open"));
    });
  }

  if (shellScrim) {
    shellScrim.addEventListener("click", () => {
      setNavigationOpen(false);
    });
  }
}

function generateId() {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  return `conv-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

function createIntroEntry() {
  return {
    role: "assistant",
    text: introMessage,
    configProposals: [],
  };
}

function normalizeTimestamp(value) {
  if (typeof value === "string") {
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toISOString();
    }
  }
  return new Date().toISOString();
}

function buildConversationTitle(text) {
  const firstLine = String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean);

  if (!firstLine) {
    return "New chat";
  }

  return firstLine.length > 56 ? `${firstLine.slice(0, 56).trimEnd()}...` : firstLine;
}

function normalizeConversationEntries(entries) {
  if (!Array.isArray(entries)) {
    return [];
  }

  return entries
    .map((entry) => {
      if (!entry || typeof entry !== "object") {
        return null;
      }

      const role = entry.role === "user" ? "user" : "assistant";
      const text = typeof entry.text === "string" ? entry.text : "";
      const configProposals = Array.isArray(entry.configProposals) ? entry.configProposals : [];
      if (!text.trim()) {
        return null;
      }
      return { role, text, configProposals };
    })
    .filter(Boolean);
}

function deriveConversationTitle(messages, fallbackTitle) {
  const firstUserMessage = messages.find((entry) => entry.role === "user");
  if (firstUserMessage) {
    return buildConversationTitle(firstUserMessage.text);
  }
  if (typeof fallbackTitle === "string" && fallbackTitle.trim()) {
    return fallbackTitle.trim();
  }
  return "New chat";
}

function createConversation(seed = {}) {
  const messages = normalizeConversationEntries(seed.messages);
  const normalizedMessages = messages.length ? messages : [createIntroEntry()];
  return {
    id: typeof seed.id === "string" && seed.id.trim() ? seed.id : generateId(),
    title: deriveConversationTitle(normalizedMessages, seed.title),
    sessionId: typeof seed.sessionId === "string" && seed.sessionId.trim() ? seed.sessionId : null,
    threadId: typeof seed.threadId === "string" && seed.threadId.trim() ? seed.threadId : null,
    draft: typeof seed.draft === "string" ? seed.draft : "",
    updatedAt: normalizeTimestamp(seed.updatedAt),
    messages: normalizedMessages,
  };
}

function isConversationPristine(conversation) {
  if (!conversation) {
    return false;
  }
  const hasUserMessage = conversation.messages.some((entry) => entry.role === "user");
  return !hasUserMessage && !conversation.threadId && !conversation.draft.trim();
}

function sortConversationsInPlace() {
  appState.conversations.sort((left, right) => {
    return new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime();
  });
}

function ensureConversationState() {
  if (!Array.isArray(appState.conversations) || appState.conversations.length === 0) {
    const hintedSessionId = body.dataset.sessionId?.trim() || null;
    const initialConversation = createConversation({ sessionId: hintedSessionId });
    appState = {
      currentConversationId: initialConversation.id,
      conversations: [initialConversation],
    };
    return;
  }

  sortConversationsInPlace();
  if (!appState.conversations.some((conversation) => conversation.id === appState.currentConversationId)) {
    appState.currentConversationId = appState.conversations[0].id;
  }
}

function migrateLegacyState(raw) {
  if (!raw || typeof raw !== "object") {
    return null;
  }

  const conversation = createConversation({
    sessionId: raw.sessionId || body.dataset.sessionId || null,
    threadId: raw.currentThreadId || null,
    draft: raw.draft || "",
    messages: raw.messages || [],
    updatedAt: raw.updatedAt,
  });

  return {
    currentConversationId: conversation.id,
    conversations: [conversation],
  };
}

function loadPersistedState() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      return JSON.parse(raw);
    }
  } catch (_error) {
    return null;
  }

  try {
    const legacyRaw = window.localStorage.getItem(LEGACY_STORAGE_KEY);
    if (!legacyRaw) {
      return null;
    }
    return migrateLegacyState(JSON.parse(legacyRaw));
  } catch (_error) {
    return null;
  }
}

function restoreState() {
  const persisted = loadPersistedState();
  if (persisted?.conversations) {
    appState = {
      currentConversationId:
        typeof persisted.currentConversationId === "string" ? persisted.currentConversationId : null,
      conversations: persisted.conversations.map((conversation) => createConversation(conversation)),
    };
  }

  ensureConversationState();
  const currentConversation = getCurrentConversation();
  body.dataset.sessionId = currentConversation?.sessionId || "";
  if (messageInput) {
    messageInput.value = currentConversation?.draft || "";
  }
  renderHistory();
  renderConversation();
  persistState();
}

function persistState() {
  const currentConversation = getCurrentConversation();
  if (currentConversation && messageInput) {
    currentConversation.draft = messageInput.value;
  }

  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(appState));
  } catch (_error) {
    // Ignore storage failures and keep the UI usable.
  }
}

function getCurrentConversation() {
  return appState.conversations.find((conversation) => conversation.id === appState.currentConversationId) || null;
}

function updateConversationTitle(conversation, messageText) {
  if (!conversation) {
    return;
  }

  if (conversation.title === "New chat") {
    conversation.title = buildConversationTitle(messageText);
  }
}

function touchConversation(conversation) {
  if (!conversation) {
    return;
  }
  conversation.updatedAt = new Date().toISOString();
}

function buildHistoryPreview(conversation) {
  const previewEntry = [...conversation.messages]
    .reverse()
    .find((entry) => entry.role === "user" || entry.text !== introMessage);

  return previewEntry?.text?.trim() || "Ready for a new question.";
}

function buildHistoryMeta(conversation) {
  const messageCount = conversation.messages.filter((entry) => entry.role === "user").length;
  const messageLabel = messageCount === 1 ? "1 question" : `${messageCount} questions`;
  return `${timestampFormatter.format(new Date(conversation.updatedAt))} · ${messageLabel}`;
}

function syncInteractiveState() {
  setDisabled(sendButton, isLoading);
  setDisabled(newChatButton, isLoading);
  setDisabled(messageInput, isLoading);
  for (const item of historyList?.querySelectorAll(".history-item, .history-delete-button") || []) {
    item.disabled = isLoading;
  }
}

function renderHistory() {
  if (!historyList) {
    return;
  }

  sortConversationsInPlace();
  historyList.innerHTML = "";

  for (const conversation of appState.conversations) {
    const row = document.createElement("div");
    row.className = "history-row";
    if (conversation.id === appState.currentConversationId) {
      row.classList.add("active");
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "history-item";

    const title = document.createElement("div");
    title.className = "history-item-title";
    title.textContent = conversation.title;

    const meta = document.createElement("div");
    meta.className = "history-item-meta";
    meta.textContent = buildHistoryMeta(conversation);

    const preview = document.createElement("div");
    preview.className = "history-item-preview";
    preview.textContent = buildHistoryPreview(conversation);

    button.appendChild(title);
    button.appendChild(meta);
    button.appendChild(preview);
    button.addEventListener("click", () => {
      if (!isLoading) {
        selectConversation(conversation.id);
      }
    });

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "history-delete-button";
    deleteButton.title = `Delete chat: ${conversation.title}`;
    deleteButton.setAttribute("aria-label", `Delete chat: ${conversation.title}`);
    deleteButton.textContent = "X";
    deleteButton.addEventListener("click", (event) => {
      event.stopPropagation();
      if (!isLoading) {
        deleteConversation(conversation.id);
      }
    });

    row.appendChild(button);
    row.appendChild(deleteButton);
    historyList.appendChild(row);
  }

  syncInteractiveState();
}

function deleteConversation(conversationId) {
  if (isLoading) {
    return;
  }

  const wasCurrent = appState.currentConversationId === conversationId;
  appState.conversations = appState.conversations.filter((conversation) => conversation.id !== conversationId);

  if (appState.conversations.length === 0) {
    const conversation = createConversation({ sessionId: body.dataset.sessionId?.trim() || null });
    appState.conversations = [conversation];
    appState.currentConversationId = conversation.id;
  } else if (wasCurrent) {
    sortConversationsInPlace();
    appState.currentConversationId = appState.conversations[0].id;
  }

  renderHistory();
  renderConversation();
  persistState();
}

function scrollMessagesToBottom() {
  if (!messages) {
    return;
  }
  messages.scrollTop = messages.scrollHeight;
}

function buildLoadingDots() {
  const dots = document.createElement("span");
  dots.className = "loading-dots";
  dots.setAttribute("aria-hidden", "true");

  for (let index = 0; index < 3; index += 1) {
    dots.appendChild(document.createElement("span"));
  }

  return dots;
}

function appendConfigProposals(article, configProposals) {
  for (const proposal of configProposals) {
    const card = document.createElement("section");
    card.className = "config-proposal";

    const title = document.createElement("h3");
    title.textContent = proposal.title;
    card.appendChild(title);

    const target = document.createElement("p");
    target.className = "config-proposal-target";
    target.textContent = `Target file: ${proposal.target_file}`;
    card.appendChild(target);

    const rationale = document.createElement("p");
    rationale.className = "config-proposal-rationale";
    rationale.textContent = proposal.rationale;
    card.appendChild(rationale);

    const code = document.createElement("pre");
    code.className = "config-proposal-code";
    code.textContent = proposal.config;
    card.appendChild(code);

    if (proposal.assumptions?.length) {
      const assumptions = document.createElement("ul");
      assumptions.className = "config-proposal-list";
      for (const item of proposal.assumptions) {
        const li = document.createElement("li");
        li.textContent = item;
        assumptions.appendChild(li);
      }
      card.appendChild(assumptions);
    }

    if (proposal.warnings?.length) {
      const warnings = document.createElement("ul");
      warnings.className = "config-proposal-list warnings";
      for (const item of proposal.warnings) {
        const li = document.createElement("li");
        li.textContent = item;
        warnings.appendChild(li);
      }
      card.appendChild(warnings);
    }

    article.appendChild(card);
  }
}

function buildMessageElement(entry, options = {}) {
  const fragment = template?.content?.cloneNode(true) || document.createDocumentFragment();
  const article = fragment.querySelector(".message") || document.createElement("article");
  let meta = article.querySelector(".message-meta") || fragment.querySelector(".message-meta");
  let content = article.querySelector(".message-body") || fragment.querySelector(".message-body");

  article.classList.add("message");

  if (!meta) {
    meta = document.createElement("div");
    meta.className = "message-meta";
    article.appendChild(meta);
  }

  if (!content) {
    content = document.createElement("div");
    content.className = "message-body";
    article.appendChild(content);
  }

  article.classList.add(entry.role);
  setText(meta, entry.role === "user" ? "You" : "KlippyAI");
  setText(content, entry.text);

  if (options.pending) {
    article.classList.add("pending");
    content.appendChild(buildLoadingDots());
  }

  if (entry.role === "assistant" && entry.configProposals?.length) {
    appendConfigProposals(article, entry.configProposals);
  }

  return article;
}

function renderConversation() {
  const conversation = getCurrentConversation();
  if (!conversation || !messages) {
    return;
  }

  messages.innerHTML = "";
  for (const entry of conversation.messages) {
    messages.appendChild(buildMessageElement(entry));
  }

  if (isLoading && loadingConversationId === conversation.id) {
    messages.appendChild(
      buildMessageElement(
        {
          role: "assistant",
          text: "Analyzing",
          configProposals: [],
        },
        { pending: true }
      )
    );
  }

  if (messageInput) {
    messageInput.value = conversation.draft || "";
  }
  body.dataset.sessionId = conversation.sessionId || "";
  scrollMessagesToBottom();
  syncInteractiveState();
}

function setComposerStatus(text) {
  setText(composerStatus, text || "");
}

function setLoadingState(nextLoading, conversationId = null) {
  isLoading = nextLoading;
  loadingConversationId = nextLoading ? conversationId : null;
  setText(sendButton, nextLoading ? "Analyzing..." : "Analyze");
  setComposerStatus(nextLoading ? "Waiting for the response..." : "");
  renderHistory();
  renderConversation();
}

function selectConversation(conversationId) {
  const currentConversation = getCurrentConversation();
  if (currentConversation && messageInput) {
    currentConversation.draft = messageInput.value;
  }

  appState.currentConversationId = conversationId;
  const nextConversation = getCurrentConversation();
  body.dataset.sessionId = nextConversation?.sessionId || "";
  renderHistory();
  renderConversation();
  persistState();
  setNavigationOpen(false);
}

function startNewChat() {
  const currentConversation = getCurrentConversation();
  if (isConversationPristine(currentConversation)) {
    messageInput?.focus();
    return;
  }

  if (currentConversation && messageInput) {
    currentConversation.draft = messageInput.value;
  }

  const conversation = createConversation();
  appState.conversations.unshift(conversation);
  appState.currentConversationId = conversation.id;
  body.dataset.sessionId = "";
  renderHistory();
  renderConversation();
  persistState();
  messageInput?.focus();
}

async function ensureSessionId(forceRefresh = false) {
  const conversation = getCurrentConversation();
  if (!conversation) {
    throw new Error("No active conversation is available.");
  }

  if (!forceRefresh && conversation.sessionId) {
    return conversation.sessionId;
  }

  const response = await fetch(`${apiBase}/ui-sessions`, {
    method: "POST",
    headers: {
      Accept: "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`Session bootstrap failed with status ${response.status}`);
  }

  const payload = await response.json();
  conversation.sessionId = payload.session_id;
  body.dataset.sessionId = conversation.sessionId;
  touchConversation(conversation);
  persistState();
  return conversation.sessionId;
}

function formatBadgeStatus(label, value) {
  const valueLabel = String(value || "unavailable").trim() || "unavailable";
  return `${label}: ${valueLabel}`;
}

function updateReachabilityBadge(badge, label, reachable) {
  if (!badge) {
    return;
  }
  badge.textContent = reachable ? `${label}: reachable` : `${label}: unavailable`;
  badge.classList.remove("ok", "warn");
  badge.classList.add(reachable ? "ok" : "warn");
}

async function bootstrap() {
  let activeSessionId = await ensureSessionId();
  let response = await fetch(`${apiBase}/bootstrap?session_id=${encodeURIComponent(activeSessionId)}`);

  if (response.status === 403) {
    activeSessionId = await ensureSessionId(true);
    response = await fetch(`${apiBase}/bootstrap?session_id=${encodeURIComponent(activeSessionId)}`);
  }

  if (!response.ok) {
    throw new Error(`Bootstrap failed with status ${response.status}`);
  }

  const payload = await response.json();
  setText(providerBadge, formatBadgeStatus("Provider", payload.provider));
  setText(modelBadge, formatBadgeStatus("Model", payload.provider_model));
  updateReachabilityBadge(moonrakerBadge, "Moonraker", Boolean(payload.moonraker_reachable));
  updateReachabilityBadge(klipperBadge, "Klipper", Boolean(payload.klipper_reachable));
  persistState();
}

async function sendMessage() {
  if (isLoading) {
    return;
  }

  const conversation = getCurrentConversation();
  if (!conversation) {
    return;
  }

  const message = messageInput?.value?.trim() || "";
  if (!message) {
    conversation.messages.push({
      role: "assistant",
      text: "Enter a question first.",
      configProposals: [],
    });
    touchConversation(conversation);
    renderConversation();
    renderHistory();
    persistState();
    return;
  }

  let activeSessionId;
  try {
    activeSessionId = await ensureSessionId();
  } catch (error) {
    conversation.messages.push({
      role: "assistant",
      text: String(error),
      configProposals: [],
    });
    touchConversation(conversation);
    renderConversation();
    renderHistory();
    persistState();
    return;
  }

  const request = {
    session_id: activeSessionId,
    message,
    artifacts: [],
  };

  if (conversation.threadId) {
    request.thread_id = conversation.threadId;
  }

  conversation.messages.push({
    role: "user",
    text: message,
    configProposals: [],
  });
  updateConversationTitle(conversation, message);
  conversation.draft = "";
  touchConversation(conversation);
  renderHistory();
  renderConversation();
  persistState();

  setLoadingState(true, conversation.id);

  try {
    let response = await fetch(`${apiBase}/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    });

    if (response.status === 403) {
      request.session_id = await ensureSessionId(true);
      response = await fetch(`${apiBase}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(request),
      });
    }

    if (!response.ok) {
      const errorBody = await response.text();
      throw new Error(`Chat failed with status ${response.status}: ${errorBody}`);
    }

    const payload = await response.json();
    conversation.threadId = payload.thread_id;
    conversation.messages.push({
      role: "assistant",
      text: payload.response,
      configProposals: payload.config_proposals || [],
    });
  } catch (error) {
    conversation.messages.push({
      role: "assistant",
      text: String(error),
      configProposals: [],
    });
  } finally {
    touchConversation(conversation);
    setLoadingState(false, null);
    renderHistory();
    renderConversation();
    persistState();
  }
}

sendButton?.addEventListener("click", () => {
  void sendMessage();
});

newChatButton?.addEventListener("click", () => {
  startNewChat();
});

messageInput?.addEventListener("input", () => {
  const conversation = getCurrentConversation();
  if (!conversation) {
    return;
  }
  conversation.draft = messageInput.value;
  persistState();
});

initializeShellNavigation();
restoreState();

void bootstrap().catch((error) => {
  const conversation = getCurrentConversation();
  if (!conversation) {
    return;
  }
  conversation.messages.push({
    role: "assistant",
    text: String(error),
    configProposals: [],
  });
  touchConversation(conversation);
  renderHistory();
  renderConversation();
  persistState();
});
