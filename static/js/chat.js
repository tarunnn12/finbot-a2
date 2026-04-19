document.addEventListener("DOMContentLoaded", () => {
    const chatMessages = document.getElementById("chatMessages");
    const chatInput = document.getElementById("chatInput");
    const sendBtn = document.getElementById("sendBtn");
    const fullscreenToggle = document.getElementById("fullscreenToggle");
    const chatShell = document.querySelector(".chat-shell");

    if (fullscreenToggle && chatShell) {
        fullscreenToggle.addEventListener("click", () => {
            chatShell.classList.toggle("is-fullscreen");
            document.body.classList.toggle("chat-fullscreen");

            if (chatShell.classList.contains("is-fullscreen")) {
                fullscreenToggle.textContent = "✕";
                fullscreenToggle.setAttribute("title", "Exit fullscreen chat");
            } else {
                fullscreenToggle.textContent = "⛶";
                fullscreenToggle.setAttribute("title", "Toggle fullscreen chat");
            }
        });
    }
    
    if (!chatMessages || !chatInput || !sendBtn) return;

    function scrollChatToBottom(force = false) {
        const distanceFromBottom =
            chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight;

        if (force || distanceFromBottom < 120) {
            requestAnimationFrame(() => {
                chatMessages.scrollTop = chatMessages.scrollHeight;
            });
        }
    }

    function setProgress(stepNumber = 1) {
        const step1 = document.getElementById("step1");
        const step2 = document.getElementById("step2");
        const step3 = document.getElementById("step3");
        const step4 = document.getElementById("step4");

        const steps = [step1, step2, step3, step4];

        steps.forEach((step, index) => {
            if (!step) return;

            if (index < stepNumber) {
                step.classList.add("active");
            } else {
                step.classList.remove("active");
            }
        });
    }

    function createMessageElement(content, sender = "bot", isHTML = false) {
        const message = document.createElement("div");
        message.className = `message ${sender}`;

        const avatar = document.createElement("div");
        avatar.className = `avatar ${sender === "bot" ? "bot-avatar" : "user-avatar"}`;
        avatar.textContent = sender === "bot" ? "🤖" : "🧑";

        const bubble = document.createElement("div");
        bubble.className = "bubble";

        if (isHTML) {
            bubble.innerHTML = content;
        } else {
            const paragraphs = String(content)
                .split("\n")
                .filter(line => line.trim() !== "");

            if (paragraphs.length === 0) {
                bubble.innerHTML = "<p></p>";
            } else {
                bubble.innerHTML = paragraphs.map(line => `<p>${escapeHtml(line)}</p>`).join("");
            }
        }

        if (sender === "user") {
            message.appendChild(bubble);
            message.appendChild(avatar);
        } else {
            message.appendChild(avatar);
            message.appendChild(bubble);
        }

        return message;
    }

    function appendMessage(content, sender = "bot", isHTML = false) {
        const messageEl = createMessageElement(content, sender, isHTML);
        chatMessages.appendChild(messageEl);
        scrollChatToBottom(true);
    }

    async function sendMessage() {
        const message = chatInput.value.trim();
        if (!message) return;

        appendMessage(message, "user", false);

        chatInput.value = "";
        autoResizeTextarea();
        chatInput.focus();

        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    message: message,
                    model: document.getElementById("modelSelect")?.value || "qwen"
                })
            });

            const data = await response.json();
            appendMessage(data.reply, "bot", data.type === "strategy");

            if (typeof data.progress === "number") {
                setProgress(data.progress);
            } else if (data.type === "strategy" || data.strategy_generated) {
                setProgress(4);
            }
        } catch (error) {
            appendMessage("Something went wrong while sending your message.", "bot", false);
            console.error(error);
        }
    }

    function autoResizeTextarea() {
        chatInput.style.height = "auto";
        chatInput.style.height = Math.min(chatInput.scrollHeight, 140) + "px";
    }

    function escapeHtml(text) {
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    sendBtn.addEventListener("click", () => sendMessage());

    chatInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    chatInput.addEventListener("input", autoResizeTextarea);

    window.quickReply = function (text) {
        chatInput.value = text;
        autoResizeTextarea();
        sendMessage();
    };

    window.resetChat = async function () {
        try {
            await fetch("/reset");

            chatMessages.innerHTML = `
                <div class="message bot">
                    <div class="avatar bot-avatar">🤖</div>
                    <div class="bubble">
                        <p><strong>Hi! I’m FinBot.</strong></p>
                        <p>I can handle two flows:</p>
                        <ul>
                            <li><strong>Market mode:</strong> “gold news”, “gold price”, “is it a good time to invest in gold?”</li>
                            <li><strong>Strategy mode:</strong> “build me a personalised investment strategy”</li>
                        </ul>
                    </div>
                </div>
            `;

            setProgress(1);

            chatInput.value = "";
            autoResizeTextarea();
            scrollChatToBottom(true);
        } catch (error) {
            console.error(error);
        }
    };

    autoResizeTextarea();
    setProgress(1);
    scrollChatToBottom(true);
});

