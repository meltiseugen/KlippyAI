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
const quickActions = document.getElementById("quick-actions");
const relatedFlow = document.getElementById("related-flow");
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
let conversationHistoryPairs = 10;

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
    sourceCitations: [],
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
      const sourceCitations = normalizeSourceCitations(entry.sourceCitations || entry.source_citations || []);
      if (!text.trim()) {
        return null;
      }
      return { role, text, configProposals, sourceCitations };
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

function getConversationText(conversation, limit = 6) {
  if (!conversation?.messages?.length) {
    return "";
  }
  return conversation.messages
    .filter((entry) => entry.text && entry.text !== introMessage)
    .slice(-limit)
    .map((entry) => entry.text)
    .join("\n");
}

function normalizeTopicLabel(value) {
  return String(value || "")
    .replace(/^\[|\]$/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function addTopicCandidate(candidates, value, score) {
  const label = normalizeTopicLabel(value);
  if (!label || label.length < 3 || label.length > 120) {
    return;
  }
  const key = label.toLowerCase();
  const existing = candidates.get(key);
  if (!existing || score > existing.score) {
    candidates.set(key, { label, score });
  }
}

function inferCurrentTopic(conversation) {
  const text = getConversationText(conversation, 8);
  if (!text) {
    return null;
  }

  const candidates = new Map();
  for (const match of text.matchAll(/`([^`\n]{3,120})`/g)) {
    const value = match[1];
    const score =
      /^\[?[A-Za-z_]+(?:\s+[A-Za-z0-9_ -]+)+\]?$/.test(value) || /^[A-Z][A-Z0-9_]{2,}$/.test(value)
        ? 6
        : 2;
    addTopicCandidate(candidates, value, score);
  }
  for (const match of text.matchAll(/\[([A-Za-z0-9_ -]+(?:\s+[A-Za-z0-9_ -]+)?)\]/g)) {
    addTopicCandidate(candidates, match[1], 5);
  }
  for (const match of text.matchAll(/\b(?:gcode_macro|filament_(?:motion|switch)_sensor|delayed_gcode|fan_generic|heater_fan|controller_fan|temperature_fan|stepper_[a-z0-9_]+|tmc[0-9a-z_]+|extruder)\s+[A-Za-z0-9_ -]+\b/gi)) {
    addTopicCandidate(candidates, match[0], 7);
  }
  for (const match of text.matchAll(/\b[A-Z][A-Z0-9_]{2,}\b/g)) {
    addTopicCandidate(candidates, match[0], 4);
  }

  const ranked = [...candidates.values()].sort((left, right) => right.score - left.score);
  return ranked[0] || null;
}

function buildQuickActionItems(topic) {
  if (!topic) {
    return [];
  }
  const target = topic.label;
  return [
    {
      label: "Locate Definition",
      prompt: `Where is ${target} defined?`,
    },
    {
      label: "Explain Usage",
      prompt: `Explain how ${target} is used.`,
    },
    {
      label: "Trace Callers",
      prompt: `Trace what calls ${target} and what ${target} calls.`,
    },
    {
      label: "Show Section",
      prompt: `Show me the full config section for ${target}.`,
    },
  ];
}

function collectFlowNodes(conversation) {
  const text = getConversationText(conversation, 8);
  if (!text) {
    return [];
  }
  const candidates = [];
  const add = (value) => {
    const label = normalizeTopicLabel(value);
    if (!label || candidates.some((item) => item.toLowerCase() === label.toLowerCase())) {
      return;
    }
    candidates.push(label);
  };

  for (const match of text.matchAll(/\bSTART_PRINT\b/g)) {
    add(match[0]);
  }
  for (const match of text.matchAll(/\bSFS_ENABLE\b/g)) {
    add(match[0]);
  }
  for (const match of text.matchAll(/\bSFS_DISABLE\b/g)) {
    add(match[0]);
  }
  for (const match of text.matchAll(/\bSET_FILAMENT_SENSOR\b/g)) {
    add(match[0]);
  }
  for (const match of text.matchAll(/\b(?:switch_sensor|encoder_sensor)\b/g)) {
    add(match[0]);
  }
  for (const match of text.matchAll(/\bM600\b/g)) {
    add(match[0]);
  }

  if (candidates.length < 2) {
    for (const match of text.matchAll(/`([^`\n]{3,80})`/g)) {
      if (/^[A-Z][A-Z0-9_]{2,}$/.test(match[1]) || /^[A-Za-z_]+(?:\s+[A-Za-z0-9_ -]+)+$/.test(match[1])) {
        add(match[1]);
      }
      if (candidates.length >= 5) {
        break;
      }
    }
  }

  return candidates.slice(0, 6);
}

function syncInteractiveState() {
  setDisabled(sendButton, isLoading);
  setDisabled(newChatButton, isLoading);
  setDisabled(messageInput, isLoading);
  for (const item of historyList?.querySelectorAll(".history-item, .history-delete-button") || []) {
    item.disabled = isLoading;
  }
  for (const item of quickActions?.querySelectorAll(".quick-action-button") || []) {
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

function normalizeHistoryPairLimit(value) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return 10;
  }
  return Math.min(parsed, 50);
}

function normalizeSourceCitations(citations) {
  if (!Array.isArray(citations)) {
    return [];
  }

  return citations
    .map((citation) => {
      if (!citation || typeof citation !== "object") {
        return null;
      }

      const label = String(citation.label || "").trim();
      const path = String(citation.path || "").trim();
      const section = String(citation.section || "").trim();
      const excerpt = String(citation.excerpt || "");
      const rawLineNumber = citation.lineNumber ?? citation.line_number;
      const parsedLineNumber = Number.parseInt(rawLineNumber, 10);
      const lineNumber = Number.isFinite(parsedLineNumber) && parsedLineNumber > 0 ? parsedLineNumber : null;

      if (!label && !path && !section && !excerpt.trim()) {
        return null;
      }

      return {
        label,
        path,
        lineNumber,
        section,
        excerpt,
      };
    })
    .filter(Boolean);
}

function buildRequestHistory(entries, pairLimit = conversationHistoryPairs) {
  const messageLimit = normalizeHistoryPairLimit(pairLimit) * 2;
  if (messageLimit <= 0) {
    return [];
  }

  return entries
    .filter((entry) => {
      const role = String(entry.role || "").trim();
      const text = String(entry.text || "").trim();
      return (role === "user" || role === "assistant") && text && text !== introMessage;
    })
    .slice(-messageLimit)
    .map((entry) => ({
      role: entry.role,
      text: String(entry.text || "").slice(0, 8000),
    }));
}

function renderRightRail(conversation) {
  if (!quickActions || !relatedFlow) {
    return;
  }

  const topic = inferCurrentTopic(conversation);
  const actionItems = buildQuickActionItems(topic);
  quickActions.innerHTML = "";

  if (!actionItems.length) {
    const empty = document.createElement("div");
    empty.className = "rail-empty";
    empty.textContent = "No config topic yet.";
    quickActions.appendChild(empty);
  } else {
    for (const item of actionItems) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "quick-action-button";
      button.textContent = item.label;
      button.title = item.prompt;
      button.disabled = isLoading;
      button.addEventListener("click", () => {
        runPrompt(item.prompt);
      });
      quickActions.appendChild(button);
    }
  }

  const nodes = collectFlowNodes(conversation);
  relatedFlow.innerHTML = "";
  if (nodes.length < 2) {
    const empty = document.createElement("div");
    empty.className = "rail-empty";
    empty.textContent = "No related flow yet.";
    relatedFlow.appendChild(empty);
    return;
  }

  for (const node of nodes) {
    const item = document.createElement("div");
    item.className = "flow-node";
    item.textContent = node;
    relatedFlow.appendChild(item);
  }
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

function appendStrongText(parent, text) {
  const parts = String(text || "").split(/(\*\*[^*]+\*\*)/g);
  for (const part of parts) {
    if (!part) {
      continue;
    }
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      const strong = document.createElement("strong");
      strong.textContent = part.slice(2, -2);
      parent.appendChild(strong);
    } else {
      parent.appendChild(document.createTextNode(part));
    }
  }
}

function appendInlineMarkdown(parent, text) {
  const parts = String(text || "").split(/(`[^`]*`)/g);
  for (const part of parts) {
    if (!part) {
      continue;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length >= 2) {
      const code = document.createElement("code");
      code.textContent = part.slice(1, -1);
      parent.appendChild(code);
    } else {
      appendStrongText(parent, part);
    }
  }
}

function isMarkdownListLine(line) {
  return /^\s*(?:[-*]\s+|\d+[.)]\s+)/.test(line);
}

function isMarkdownHeadingLine(line) {
  return /^\s{0,3}#{1,4}\s+/.test(line);
}

function isMarkdownFenceLine(line) {
  return /^\s*```/.test(line);
}

function renderMarkdown(element, text) {
  element.textContent = "";
  const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fenceMatch = line.match(/^\s*```([A-Za-z0-9_-]+)?\s*$/);
    if (fenceMatch) {
      index += 1;
      const codeLines = [];
      while (index < lines.length && !isMarkdownFenceLine(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }

      const pre = document.createElement("pre");
      pre.className = "markdown-code";
      const code = document.createElement("code");
      if (fenceMatch[1]) {
        code.dataset.language = fenceMatch[1];
      }
      code.textContent = codeLines.join("\n");
      pre.appendChild(code);
      element.appendChild(pre);
      continue;
    }

    const headingMatch = line.match(/^\s{0,3}(#{1,4})\s+(.+?)\s*$/);
    if (headingMatch) {
      const level = Math.min(headingMatch[1].length + 2, 6);
      const heading = document.createElement(`h${level}`);
      appendInlineMarkdown(heading, headingMatch[2]);
      element.appendChild(heading);
      index += 1;
      continue;
    }

    if (isMarkdownListLine(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const list = document.createElement(ordered ? "ol" : "ul");
      while (index < lines.length) {
        const itemLine = lines[index];
        const itemMatch = ordered
          ? itemLine.match(/^\s*\d+[.)]\s+(.+?)\s*$/)
          : itemLine.match(/^\s*[-*]\s+(.+?)\s*$/);
        if (!itemMatch) {
          break;
        }
        const item = document.createElement("li");
        appendInlineMarkdown(item, itemMatch[1]);
        list.appendChild(item);
        index += 1;
      }
      element.appendChild(list);
      continue;
    }

    const paragraphLines = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !isMarkdownFenceLine(lines[index]) &&
      !isMarkdownHeadingLine(lines[index]) &&
      !isMarkdownListLine(lines[index])
    ) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    const paragraph = document.createElement("p");
    appendInlineMarkdown(paragraph, paragraphLines.join(" "));
    element.appendChild(paragraph);
  }
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

function formatSourceCitationLabel(citation) {
  if (citation.label) {
    return citation.label;
  }
  const section = citation.section ? ` [${citation.section}]` : "";
  if (citation.path && citation.lineNumber) {
    return `${citation.path}:${citation.lineNumber}${section}`;
  }
  return citation.path ? `${citation.path}${section}` : citation.section || "Config source";
}

function appendSourceCitations(article, sourceCitations) {
  const citations = normalizeSourceCitations(sourceCitations);
  if (!citations.length) {
    return;
  }

  const section = document.createElement("section");
  section.className = "source-citations";
  section.setAttribute("aria-label", "Sources");

  const title = document.createElement("div");
  title.className = "source-citations-title";
  title.textContent = "Sources";
  section.appendChild(title);

  const list = document.createElement("div");
  list.className = "source-citations-list";

  for (const citation of citations) {
    const item = document.createElement("details");
    item.className = "source-citation";

    const summary = document.createElement("summary");
    summary.textContent = formatSourceCitationLabel(citation);
    item.appendChild(summary);

    const excerpt = document.createElement("pre");
    excerpt.className = "source-citation-excerpt";
    excerpt.textContent = citation.excerpt?.trim() || "No section excerpt was available in the collected config.";
    item.appendChild(excerpt);

    list.appendChild(item);
  }

  section.appendChild(list);
  article.appendChild(section);
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
  content.classList.toggle("markdown", entry.role === "assistant");
  if (entry.role === "assistant") {
    renderMarkdown(content, entry.text);
  } else {
    setText(content, entry.text);
  }

  if (options.pending) {
    article.classList.add("pending");
    content.appendChild(buildLoadingDots());
  }

  if (entry.role === "assistant" && entry.configProposals?.length) {
    appendConfigProposals(article, entry.configProposals);
  }

  if (entry.role === "assistant" && entry.sourceCitations?.length) {
    appendSourceCitations(article, entry.sourceCitations);
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
          sourceCitations: [],
        },
        { pending: true }
      )
    );
  }

  if (messageInput) {
    messageInput.value = conversation.draft || "";
  }
  body.dataset.sessionId = conversation.sessionId || "";
  renderRightRail(conversation);
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
  conversationHistoryPairs = normalizeHistoryPairLimit(payload.conversation_history_pairs);
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
      sourceCitations: [],
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
      sourceCitations: [],
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
    history: buildRequestHistory(conversation.messages),
  };

  if (conversation.threadId) {
    request.thread_id = conversation.threadId;
  }

  conversation.messages.push({
    role: "user",
    text: message,
    configProposals: [],
    sourceCitations: [],
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
      sourceCitations: normalizeSourceCitations(payload.source_citations || []),
    });
  } catch (error) {
    conversation.messages.push({
      role: "assistant",
      text: String(error),
      configProposals: [],
      sourceCitations: [],
    });
  } finally {
    touchConversation(conversation);
    setLoadingState(false, null);
    renderHistory();
    renderConversation();
    persistState();
  }
}

function runPrompt(prompt) {
  if (isLoading || !messageInput) {
    return;
  }
  const conversation = getCurrentConversation();
  if (!conversation) {
    return;
  }
  messageInput.value = prompt;
  conversation.draft = prompt;
  persistState();
  void sendMessage();
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
    sourceCitations: [],
  });
  touchConversation(conversation);
  renderHistory();
  renderConversation();
  persistState();
});
