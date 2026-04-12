# ============================================================
# COMP8420 A2 — Flask Web Application
# FinBot: Smart Personal Financial Assistant
# Student: Tarun Verma | ID: 49030000
# ============================================================

import os
import json
from flask import Flask, render_template, request, jsonify, session
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory

# ── Load environment variables ──────────────────────────────
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

# ── Flask App Setup ─────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.urandom(24)

# ── LLM Setup ───────────────────────────────────────────────
llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.7,
    openai_api_key=os.getenv("OPENAI_API_KEY")
)

# ── System Prompt with CoT ──────────────────────────────────
system_prompt = """
You are FinBot, a smart and friendly personal financial assistant.
Your goal is to collect information from the user step by step and
provide personalised financial strategies.

Follow this structured dialogue flow:
1. Greet the user and ask what financial help they need
2. Collect personal details: age, annual income, current savings, employment status
3. Collect financial preferences: risk tolerance (low/moderate/high),
   investment goals, and timeframe
4. Once all information is collected, use Chain-of-Thought reasoning:
   - Think through their financial situation step by step
   - Consider their risk tolerance and goals
   - Generate a structured, personalised financial strategy

Rules:
- Be friendly, professional and concise
- Do not repeat questions already answered
- If employment status is not provided, assume full-time
- When you have enough information, provide a structured recommendation with
  these exact sections:
  EMERGENCY FUND:
  INVESTMENT STRATEGY:
  SAVINGS PLAN:
  RISK MANAGEMENT:
  10-YEAR ROADMAP:
- After giving the full strategy, add this exact line at the end:
  [STRATEGY_COMPLETE]
"""

# ── Prompt Template ─────────────────────────────────────────
prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    MessagesPlaceholder(variable_name="history"),
    ("human", "{input}")
])

# ── Chain ────────────────────────────────────────────────────
chain = prompt | llm

# ── Session Memory Store ─────────────────────────────────────
session_store = {}

def get_session_history(session_id: str) -> ChatMessageHistory:
    if session_id not in session_store:
        session_store[session_id] = ChatMessageHistory()
    return session_store[session_id]

# ── Dialogue Chain ───────────────────────────────────────────
dialogue_chain = RunnableWithMessageHistory(
    chain,
    get_session_history,
    input_messages_key="input",
    history_messages_key="history"
)

# ============================================================
# ROUTES
# ============================================================

# ── Home Page ────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


# ── Chat Page ────────────────────────────────────────────────
@app.route("/chat")
def chat_page():
    # Generate unique session ID for each user
    if "session_id" not in session:
        session["session_id"] = os.urandom(8).hex()
    # Clear previous session memory
    sid = session["session_id"]
    if sid in session_store:
        del session_store[sid]
    return render_template("chat.html")


# ── Chat API ─────────────────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    sid = session.get("session_id", "default")

    try:
        config = {"configurable": {"session_id": sid}}
        response = dialogue_chain.invoke(
            {"input": user_message},
            config=config
        )
        bot_reply = response.content

        # Check if strategy is complete
        strategy_complete = "[STRATEGY_COMPLETE]" in bot_reply
        bot_reply = bot_reply.replace("[STRATEGY_COMPLETE]", "").strip()

        # If strategy complete, extract and store it
        if strategy_complete:
            session["strategy"] = bot_reply
            session.modified = True

        return jsonify({
            "reply": bot_reply,
            "strategy_complete": strategy_complete
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Results Page ─────────────────────────────────────────────
@app.route("/results")
def results():
    strategy = session.get("strategy", None)
    if not strategy:
        return render_template("results.html", strategy=None)
    return render_template("results.html", strategy=strategy)


# ── Reset Session ────────────────────────────────────────────
@app.route("/reset")
def reset():
    sid = session.get("session_id")
    if sid and sid in session_store:
        del session_store[sid]
    session.clear()
    return jsonify({"status": "reset"})


# ============================================================
if __name__ == "__main__":
     port = int(os.environ.get("PORT", 5000))
     app.run(debug=False, host="0.0.0.0", port=port)