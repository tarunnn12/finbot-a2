/* ============================================================
   COMP8420 A2 — FinBot Chat JavaScript
   Student: Tarun Verma | ID: 49030000
   ============================================================ */

let messageCount = 0;

// ── Send Message ─────────────────────────────────────────────
async function sendMessage() {
    const input = document.getElementById("chatInput");
    const message = input.value.trim();
    if (!message) return;

    // Add user message
    appendMessage(message, "user");
    input.value = "";
    input.style.height = "auto";

    // Disable input while waiting
    toggleInput(false);

    // Show typing indicator
    const typingId = showTyping();

    try {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message })
        });

        const data = await response.json();
        removeTyping(typingId);

        if (data.error) {
            appendMessage("Sorry, something went wrong. Please try again.", "bot");
        } else {
            appendMessage(data.reply, "bot");
            updateProgress(messageCount);

            // If strategy complete redirect to results
            if (data.strategy_complete) {
                updateStep(4);
                setTimeout(() => {
                    appendMessage("✅ Your financial strategy is ready! Redirecting to results...", "bot");
                    setTimeout(() => window.location.href = "/results", 2000);
                }, 500);
            }
        }
    } catch (err) {
        removeTyping(typingId);
        appendMessage("Connection error. Please check your internet and try again.", "bot");
    }

    toggleInput(true);
}

// ── Append Message ───────────────────────────────────────────
function appendMessage(text, sender) {
    const container = document.getElementById("chatMessages");
    messageCount++;

    const div = document.createElement("div");
    div.className = `message ${sender}`;
    div.innerHTML = `
        <div class="message-avatar ${sender}-avatar">
            ${sender === "bot" ? "🤖" : "👤"}
        </div>
        <div class="message-bubble">${formatMessage(text)}</div>
    `;

    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

// ── Format Message (bold, line breaks) ──────────────────────
function formatMessage(text) {
    return text
        .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
        .replace(/\*(.*?)\*/g, "<em>$1</em>")
        .replace(/\n/g, "<br/>");
}

// ── Typing Indicator ─────────────────────────────────────────
function showTyping() {
    const container = document.getElementById("chatMessages");
    const id = "typing-" + Date.now();
    const div = document.createElement("div");
    div.className = "message bot";
    div.id = id;
    div.innerHTML = `
        <div class="message-avatar bot-avatar">🤖</div>
        <div class="typing-indicator">
            <span></span><span></span><span></span>
        </div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return id;
}

function removeTyping(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

// ── Toggle Input ─────────────────────────────────────────────
function toggleInput(enabled) {
    const input = document.getElementById("chatInput");
    const btn = document.getElementById("sendBtn");
    input.disabled = !enabled;
    btn.disabled = !enabled;
}

// ── Quick Reply ──────────────────────────────────────────────
function quickReply(text) {
    const input = document.getElementById("chatInput");
    input.value = text;
    sendMessage();
}

// ── Update Progress Steps ────────────────────────────────────
function updateProgress(count) {
    if (count >= 1) updateStep(1);
    if (count >= 3) updateStep(2);
    if (count >= 5) updateStep(3);
}

function updateStep(stepNum) {
    for (let i = 1; i <= 4; i++) {
        const el = document.getElementById("step" + i);
        if (!el) continue;
        if (i < stepNum) {
            el.className = "step done";
        } else if (i === stepNum) {
            el.className = "step active";
        } else {
            el.className = "step";
        }
    }
}

// ── Reset Chat ───────────────────────────────────────────────
async function resetChat() {
    await fetch("/reset");
    window.location.reload();
}

// ── Enter Key to Send ────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    const input = document.getElementById("chatInput");
    if (!input) return;
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Auto resize textarea
    input.addEventListener("input", () => {
        input.style.height = "auto";
        input.style.height = input.scrollHeight + "px";
    });
});