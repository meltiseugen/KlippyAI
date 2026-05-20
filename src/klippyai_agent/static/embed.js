const body = document.body;
const sessionId = body.dataset.sessionId;
const apiBase = body.dataset.apiBase;
const messages = document.getElementById("messages");
const providerBadge = document.getElementById("provider-badge");
const moonrakerBadge = document.getElementById("moonraker-badge");
const profileBadge = document.getElementById("profile-badge");
const sendButton = document.getElementById("send-button");
const messageInput = document.getElementById("message-input");
const artifactInput = document.getElementById("artifact-input");
const artifactKind = document.getElementById("artifact-kind");
const artifactLabel = document.getElementById("artifact-label");
const template = document.getElementById("message-template");
const shellMenuToggle = document.getElementById("shell-menu-toggle");
const shellScrim = document.getElementById("shell-scrim");
const shellNavLinks = Array.from(document.querySelectorAll(".sidebar-nav a"));
let currentThreadId = null;

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

  for (const link of shellNavLinks) {
    link.addEventListener("click", () => {
      setNavigationOpen(false);
    });
  }
}

function appendMessage(role, text) {
  const fragment = template.content.cloneNode(true);
  const article = fragment.querySelector(".message");
  article.classList.add(role);
  fragment.querySelector(".message-meta").textContent = role;
  fragment.querySelector(".message-body").textContent = text;
  messages.appendChild(fragment);
  messages.scrollTop = messages.scrollHeight;
}

function appendAssistantPayload(payload) {
  const fragment = template.content.cloneNode(true);
  const article = fragment.querySelector(".message");
  article.classList.add("assistant");
  fragment.querySelector(".message-meta").textContent = "assistant";
  fragment.querySelector(".message-body").textContent = payload.response;

  if (payload.config_proposals?.length) {
    for (const proposal of payload.config_proposals) {
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

  messages.appendChild(fragment);
  messages.scrollTop = messages.scrollHeight;
}

function summarizeProfile(profile) {
  if (!profile) {
    return "Profile: unavailable";
  }
  if (profile.summary) {
    return `Profile: ${profile.summary}`;
  }
  const parts = [];
  if (profile.firmware_flavor) {
    parts.push(profile.firmware_flavor);
  }
  if (profile.canbus_enabled) {
    parts.push("CAN");
  }
  if (profile.addons?.length) {
    parts.push(profile.addons.slice(0, 2).map((addon) => addon.name).join(", "));
  }
  return parts.length ? `Profile: ${parts.join(" | ")}` : "Profile: unavailable";
}

async function bootstrap() {
  const response = await fetch(`${apiBase}/bootstrap?session_id=${encodeURIComponent(sessionId)}`);
  if (!response.ok) {
    throw new Error(`Bootstrap failed with status ${response.status}`);
  }
  const payload = await response.json();
  providerBadge.textContent = `Provider: ${payload.provider}`;
  moonrakerBadge.textContent = payload.moonraker_reachable
    ? "Moonraker: reachable"
    : "Moonraker: unavailable";
  moonrakerBadge.classList.add(payload.moonraker_reachable ? "ok" : "warn");
  profileBadge.textContent = summarizeProfile(payload.printer_profile);
}

async function sendMessage() {
  const message = messageInput.value.trim();
  const artifact = artifactInput.value.trim();

  if (!message) {
    appendMessage("assistant", "Enter a question first.");
    return;
  }

  const request = {
    session_id: sessionId,
    message,
    artifacts: [],
  };

  if (currentThreadId) {
    request.thread_id = currentThreadId;
  }

  if (artifact) {
    request.artifacts.push({
      kind: artifactKind.value,
      label: artifactLabel.value.trim() || "clipboard",
      content: artifact,
    });
  }

  appendMessage("user", message);
  sendButton.disabled = true;

  try {
    const response = await fetch(`${apiBase}/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      const errorBody = await response.text();
      throw new Error(`Chat failed with status ${response.status}: ${errorBody}`);
    }

    const payload = await response.json();
    currentThreadId = payload.thread_id;
    appendAssistantPayload(payload);
    messageInput.value = "";
  } catch (error) {
    appendMessage("assistant", String(error));
  } finally {
    sendButton.disabled = false;
  }
}

sendButton.addEventListener("click", () => {
  void sendMessage();
});

initializeShellNavigation();

void bootstrap().catch((error) => {
  appendMessage("assistant", String(error));
});
