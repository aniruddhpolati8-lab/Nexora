const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");
const chatMessages = document.getElementById("chatMessages");
const newChatButton = document.getElementById("newChatButton");
const sendButton = chatForm.querySelector(".send-button");
const menuButton = document.getElementById("menuButton");
const closeSidebar = document.getElementById("closeSidebar");
const sidebar = document.getElementById("sidebar");
const sidebarOverlay = document.getElementById("sidebarOverlay");
const historyItems = document.querySelectorAll(".history-item");

let isSending = false;

const CHAT_ENDPOINT = "https://nexora-intelligence-reimagined.onrender.com/chat";
const REQUEST_TIMEOUT = 60000;
const welcomeMarkup = chatMessages.innerHTML;

function addMessage(message, type) {
  const element = document.createElement("div");
  element.className = `message ${type}-message`;
  element.textContent = message;
  element.setAttribute("role", type === "agent" ? "status" : "none");

  chatMessages.appendChild(element);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return element;
}

function setLoading(loading) {
  isSending = loading;
  sendButton.disabled = loading;
  chatInput.disabled = loading;
  sendButton.setAttribute("aria-busy", String(loading));
  sendButton.classList.toggle("is-loading", loading);
}

function addTyping() {
  const typing = document.createElement("div");
  typing.className = "typing";
  typing.setAttribute("role", "status");
  typing.setAttribute("aria-live", "polite");
  typing.setAttribute("aria-label", "Nexora is thinking");
  typing.textContent = "Nexora is thinking";

  chatMessages.appendChild(typing);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return typing;
}

async function getAgentReply(message) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);

  try {
    const response = await fetch(CHAT_ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json, text/plain"
      },
      body: JSON.stringify({ message }),
      signal: controller.signal
    });

    const responseText = await response.text();

    if (!response.ok) {
      throw new Error(
        `The backend returned HTTP ${response.status}${
          responseText ? `: ${responseText.slice(0, 240)}` : "."
        }`
      );
    }

    if (!responseText.trim()) {
      throw new Error("The backend returned an empty response.");
    }

    let data;

    try {
      data = JSON.parse(responseText);
    } catch {
      return responseText.trim();
    }

    const reply =
      data.reply ??
      data.response ??
      data.answer ??
      data.message ??
      data.output;

    if (typeof reply !== "string" || !reply.trim()) {
      throw new Error(
        "The /chat response must contain reply, response, answer, message, or output."
      );
    }

    return reply.trim();
  } catch (error) {
    if (error.name === "AbortError") {
      error.code = "BACKEND_TIMEOUT";
      error.message = "The backend timed out while responding.";
    } else if (error instanceof TypeError) {
      error.code = "BACKEND_UNREACHABLE";
      error.message = "The backend could not be reached.";
    }

    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

function getBackendErrorMessage(error) {
  if (error.code === "BACKEND_TIMEOUT") {
    return "The backend took too long to respond. Please try again.";
  }

  if (error.code === "BACKEND_UNREACHABLE") {
    return "The backend could not be reached. Check that the Render service is running.";
  }

  return `The backend returned an error: ${error.message}`;
}

async function sendMessage(message) {
  const cleanMessage = message.trim();

  if (!cleanMessage || isSending) return;

  addMessage(cleanMessage, "user");
  chatInput.value = "";
  resizeInput();
  setLoading(true);

  const typing = addTyping();

  try {
    const reply = await getAgentReply(cleanMessage);
    typing.remove();
    addMessage(reply, "agent");
  } catch (error) {
    console.error("Nexora /chat request failed:", error);
    typing.remove();
    addMessage(getBackendErrorMessage(error), "agent");
  } finally {
    setLoading(false);
    chatInput.focus();
  }
}

function newChat() {
  chatMessages.innerHTML = welcomeMarkup;
  chatInput.value = "";
  resizeInput();
  bindPromptCards();
  chatInput.focus();
}

function bindPromptCards() {
  document.querySelectorAll(".prompt-card").forEach((card) => {
    card.addEventListener("click", () => {
      chatInput.value = card.dataset.prompt;
      resizeInput();
      chatInput.focus();
    });
  });
}

function toggleSidebar(show) {
  sidebar.classList.toggle("open", show);
  sidebarOverlay.classList.toggle("visible", show);
  menuButton.setAttribute("aria-expanded", String(show));
}

function resizeInput() {
  chatInput.style.height = "auto";
  chatInput.style.height = `${Math.min(chatInput.scrollHeight, 120)}px`;
}

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(chatInput.value);
});

chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

chatInput.addEventListener("input", resizeInput);

newChatButton.addEventListener("click", newChat);
menuButton.addEventListener("click", () => toggleSidebar(true));
closeSidebar.addEventListener("click", () => toggleSidebar(false));
sidebarOverlay.addEventListener("click", () => toggleSidebar(false));

document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    newChat();
  }

  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault();
    chatForm.requestSubmit();
  }

  if (event.key === "Escape") {
    toggleSidebar(false);
  }
});

historyItems.forEach((item) => {
  item.addEventListener("click", () => {
    historyItems.forEach((historyItem) => {
      historyItem.classList.remove("active");
    });

    item.classList.add("active");
    toggleSidebar(false);
  });
});

bindPromptCards();
resizeInput();
