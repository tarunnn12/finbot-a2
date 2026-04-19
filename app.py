import json
import os
import re
from html import escape

import requests
import yfinance as yf
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session
from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "finbot_dev_secret")

# =========================
# MODELS
# =========================
llm_qwen = ChatOllama(model="qwen2.5:3b", temperature=0.1)
llm_openai = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.1,
    openai_api_key=os.getenv("OPENAI_API_KEY")
)


def get_llm(choice: str):
    return llm_openai if choice == "openai" else llm_qwen


# =========================
# STATE
# =========================
user_profiles = {}

REQUIRED_FIELDS = [
    "income",
    "monthly_expenses",
    "current_savings",
    "yearly_savings_capacity",
    "risk",
    "goal",
    "timeframe",
]

FIELD_QUESTIONS = {
    "income": "What is your annual income?",
    "monthly_expenses": "What are your average monthly expenses?",
    "current_savings": "How much do you currently have saved?",
    "yearly_savings_capacity": "How much can you save each year apart from your current savings?",
    "risk": "What is your risk tolerance — low, moderate, or high?",
    "goal": "What is your main financial goal?",
    "timeframe": "How many years do you have to achieve this goal?",
}

NEWS_API_KEY = os.getenv("NEWS_API_KEY")


# =========================
# HELPERS
# =========================
def get_session_id() -> str:
    sid = session.get("session_id")
    if not sid:
        sid = os.urandom(8).hex()
        session["session_id"] = sid
    if sid not in user_profiles:
        user_profiles[sid] = {}
    return sid



def normalize_text(message: str) -> str:
    return (message or "").strip().lower()



def is_greeting(message: str) -> bool:
    text = normalize_text(message)
    greetings = ["hi", "hello", "hey", "good morning", "good evening", "my name is", "i am", "i'm"]
    return any(text.startswith(g) for g in greetings)



def detect_symbol(text: str):
    value = normalize_text(text)
    mapping = {
        "gold": ("GLD", "gold"),
        "gld": ("GLD", "gold"),
        "tesla": ("TSLA", "tesla"),
        "tsla": ("TSLA", "tesla"),
        "apple": ("AAPL", "apple"),
        "aapl": ("AAPL", "apple"),
        "bitcoin": ("BTC-USD", "bitcoin"),
        "btc": ("BTC-USD", "bitcoin"),
        "spy": ("SPY", "market"),
        "s&p 500": ("SPY", "market"),
        "s&p500": ("SPY", "market"),
    }
    for key, result in mapping.items():
        if key in value:
            return result
    return (None, "market")



def is_market_query(message: str) -> bool:
    text = normalize_text(message)
    keywords = [
        "price", "news", "market", "outlook", "what's happening", "whats happening",
        "is it a good time", "good time to invest", "should i buy", "should i invest",
        "gold", "tesla", "bitcoin", "apple", "stock", "crypto"
    ]
    return any(k in text for k in keywords)



def is_strategy_request(message: str) -> bool:
    text = normalize_text(message)
    keywords = [
        "strategy", "plan", "portfolio", "allocation", "roadmap", "build me a plan",
        "create a strategy", "make a plan", "investment plan", "personalised strategy",
        "retirement plan", "house deposit plan"
    ]
    strong_strategy = any(k in text for k in keywords)
    soft_market_only = any(k in text for k in ["is it a good time", "should i buy", "should i invest"])
    return strong_strategy and not soft_market_only



def should_answer_market_view(message: str) -> bool:
    text = normalize_text(message)
    return any(k in text for k in ["is it a good time", "should i buy", "should i invest", "outlook", "news", "price"])



def safe_float(value):
    try:
        return float(value)
    except Exception:
        return None



def parse_field_input(text: str, field: str):
    if not isinstance(text, str):
        return None

    value = text.strip().lower().replace(",", "").replace("$", "")

    if field in {"income", "monthly_expenses", "current_savings", "yearly_savings_capacity"}:
        if value.endswith("k"):
            try:
                return float(value[:-1]) * 1000
            except Exception:
                return None
        return safe_float(value)

    if field == "timeframe":
        match = re.search(r"\d+", value)
        return int(match.group()) if match else None

    if field == "risk":
        if value in {"low", "moderate", "high"}:
            return value
        return None

    return text.strip()



def get_missing_fields(profile: dict):
    missing = []
    for field in REQUIRED_FIELDS:
        current = profile.get(field)
        if current is None or (isinstance(current, str) and not current.strip()):
            missing.append(field)
    return missing



def extract_user_data(message: str, existing_profile: dict, model_choice: str):
    llm = get_llm(model_choice)
    prompt = f"""
Extract financial details from the user's message.

Existing profile:
{json.dumps(existing_profile, indent=2)}

User message:
{message}

Extract ONLY these keys if the user explicitly gave them:
income, monthly_expenses, current_savings, yearly_savings_capacity, risk, goal, timeframe

Return ONLY valid JSON. Example:
{{
  "income": 90000,
  "current_savings": 12000,
  "risk": "moderate",
  "goal": "save for a house deposit",
  "timeframe": 5
}}
"""
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = (response.content or "").strip()
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


# =========================
# MARKET DATA / NEWS
# =========================
def is_relevant_gold_headline(title: str, description: str = "") -> bool:
    text = f"{title} {description}".lower()
    if "gold" not in text:
        return False
    bad_terms = [
        "jewellery", "jewelry", "wedding", "temple", "festival", "medal",
        "donation", "donate", "piggy bank", "ornament", "charity"
    ]
    if any(term in text for term in bad_terms):
        return False
    good_terms = [
        "price", "bullion", "etf", "market", "inflation", "interest rate",
        "treasury", "federal reserve", "central bank", "safe haven", "commodity"
    ]
    return any(term in text for term in good_terms)



def fetch_news(query: str, asset_type: str = "general"):
    if not NEWS_API_KEY:
        return []

    try:
        response = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "sortBy": "publishedAt",
                "language": "en",
                "pageSize": 8,
                "apiKey": NEWS_API_KEY,
            },
            timeout=10,
        )
        data = response.json()
        items = []
        for article in data.get("articles", []):
            title = article.get("title", "")
            description = article.get("description", "") or ""
            if not title:
                continue

            text = f"{title} {description}".lower()
            if asset_type == "gold":
                if not is_relevant_gold_headline(title, description):
                    continue
            elif asset_type == "tesla":
                if not any(k in text for k in ["tesla", "deliveries", "margin", "earnings", "ev", "stock"]):
                    continue
            elif asset_type == "apple":
                if not any(k in text for k in ["apple", "iphone", "earnings", "services", "stock"]):
                    continue
            elif asset_type == "bitcoin":
                if not any(k in text for k in ["bitcoin", "crypto", "etf", "regulation", "fed"]):
                    continue
            items.append(title)
        return items[:3]
    except Exception as exc:
        print("NEWS ERROR:", exc)
        return []



def get_ticker_snapshot(ticker: str):
    try:
        data = yf.download(ticker, period="1mo", progress=False, auto_adjust=False)
        if data.empty or "Close" not in data:
            return None

        close = data["Close"]
        if getattr(close, "ndim", 1) > 1:
            close = close.squeeze()
        if close.empty:
            return None

        latest = float(close.iloc[-1])
        week_base = float(close.iloc[-5]) if len(close) >= 5 else float(close.iloc[0])
        month_base = float(close.iloc[0])
        week_change = ((latest - week_base) / week_base * 100) if week_base else 0
        month_change = ((latest - month_base) / month_base * 100) if month_base else 0

        return {
            "ticker": ticker,
            "price": round(latest, 2),
            "week_change": round(week_change, 2),
            "month_change": round(month_change, 2),
        }
    except Exception as exc:
        print(f"YF ERROR for {ticker}: {exc}")
        return None



def get_live_market_snapshot():
    labels = {
        "SPY": "S&P 500",
        "GLD": "Gold ETF",
        "BTC-USD": "Bitcoin",
        "AAPL": "Apple",
        "TSLA": "Tesla",
    }
    results = []
    for ticker, label in labels.items():
        snap = get_ticker_snapshot(ticker)
        if snap:
            results.append(f"{label}: ${snap['price']} ({snap['week_change']}% 1w, {snap['month_change']}% 1m)")
    return "\n".join(results) if results else "Market snapshot is temporarily unavailable."



def build_live_context(message: str):
    ticker, asset = detect_symbol(message)
    snapshot = get_ticker_snapshot(ticker) if ticker else None
    market = get_live_market_snapshot()

    if asset == "gold":
        news = fetch_news("gold price OR spot gold OR bullion OR federal reserve OR central bank gold", asset_type="gold")
    elif asset == "tesla":
        news = fetch_news("tesla stock OR tesla earnings OR tesla deliveries", asset_type="tesla")
    elif asset == "apple":
        news = fetch_news("apple stock OR apple earnings OR iphone sales", asset_type="apple")
    elif asset == "bitcoin":
        news = fetch_news("bitcoin price OR bitcoin ETF OR crypto regulation", asset_type="bitcoin")
    else:
        news = fetch_news("stock market OR inflation OR interest rates OR federal reserve")

    if not news:
        if asset == "gold":
            news = ["No strong gold-specific headline is dominating right now, so the short-term view is mostly being driven by inflation, yields, and central-bank expectations."]
        else:
            news = ["No single headline stands out right now, so the near-term market view is being driven mostly by rates, inflation, and growth expectations."]

    return {
        "ticker": ticker,
        "asset": asset,
        "snapshot": snapshot,
        "market": market,
        "news": news,
    }



def answer_market_question(message: str, model_choice: str):
    llm = get_llm(model_choice)
    context = build_live_context(message)

    prompt = f"""
You are FinBot, a practical financial assistant.

User question:
{message}

Asset detected: {context['asset']}
Ticker snapshot:
{json.dumps(context['snapshot'], indent=2) if context['snapshot'] else 'No direct asset snapshot available'}

Broader market snapshot:
{context['market']}

News context:
{json.dumps(context['news'], indent=2)}

Instructions:
- Give a natural answer in plain English.
- If the user asked for price, include the latest price first.
- If the user asked "is it a good time to invest" or "should I buy", give a generic market-based view, not a personalised plan.
- Use the live price move and news context.
- Mention uncertainty where appropriate.
- Do not ask for profile questions unless the user explicitly asks for a strategy or plan.
- Keep it concise but useful.
- Do not output JSON.
"""
    response = llm.invoke([HumanMessage(content=prompt)])
    return (response.content or "I couldn't generate a market summary right now.").strip()


# =========================
# STRATEGY
# =========================
def generate_strategy(profile: dict, model_choice: str):
    monthly_expenses = float(profile["monthly_expenses"])
    current_savings = float(profile["current_savings"])
    yearly_savings_capacity = float(profile["yearly_savings_capacity"])
    monthly_savings = round(yearly_savings_capacity / 12, 2)
    emergency_target = round(monthly_expenses * 6, 2)
    gap = round(max(emergency_target - current_savings, 0), 2)
    coverage_pct = round(min((current_savings / emergency_target) * 100, 100), 1) if emergency_target else 100.0
    months_to_close = round(gap / monthly_savings, 1) if monthly_savings > 0 and gap > 0 else 0.0

    market_context = build_live_context(profile.get("goal", "gold strategy"))
    llm = get_llm(model_choice)

    prompt = f"""
You are a practical personal finance assistant.

User profile:
{json.dumps(profile, indent=2)}

Recent market context:
{market_context['market']}

Relevant news:
{json.dumps(market_context['news'], indent=2)}

Use these exact numbers:
- monthly_expenses = {monthly_expenses}
- emergency_target = {emergency_target}
- current_savings = {current_savings}
- gap = {gap}
- coverage_pct = {coverage_pct}
- monthly_savings = {monthly_savings}
- months_to_close = {months_to_close}

Return ONLY valid JSON using exactly this structure:
{{
  "summary": "2-3 sentence personalised overview",
  "emergency_fund_title": "short title",
  "emergency_fund": "Explain why an emergency fund matters, include each numbered calculation step, and conclude clearly whether to prioritise this before investing.",
  "strategy_title": "short title",
  "strategy": "Concrete personalised investment strategy. Be specific about what to do, what to avoid, and how to phase money deployment.",
  "allocation_title": "short title",
  "allocation": "Give a concrete percentage split adding to 100% and explain why.",
  "risk_title": "short title",
  "risk_note": "Explain key risks and safeguards in a concrete way.",
  "roadmap_title": "short title",
  "roadmap": ["step 1", "step 2", "step 3", "step 4"],
  "emergency_fund_calc": {{
    "monthly_expenses": {monthly_expenses},
    "emergency_target": {emergency_target},
    "current_savings": {current_savings},
    "gap": {gap},
    "coverage_pct": {coverage_pct},
    "monthly_savings": {monthly_savings},
    "months_to_close": {months_to_close}
  }}
}}

Quality requirements:
- No vague statements like "diversified portfolio" unless you say what it includes.
- Tie the recommendation to risk level, goal, and timeframe.
- If goal is house deposit and risk is low, prefer capital preservation over aggressive growth.
- If gold is mentioned, explain whether it should be a hedge or a core holding.
- Keep tone professional and direct.
"""

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = (response.content or "").strip()
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        parsed = json.loads(raw)
        return parsed
    except Exception:
        goal = str(profile.get("goal", "your goal")).strip()
        risk = str(profile.get("risk", "moderate")).strip()
        fallback_strategy = (
            f"Because your goal is {goal} and your risk tolerance is {risk}, the plan should focus first on cash safety and disciplined monthly investing. "
            f"Until your emergency fund is complete, direct most new savings into that buffer. After that, if you still want gold exposure, keep it as a smaller satellite position through a liquid gold ETF rather than making it your entire portfolio. "
            f"For a low-risk goal such as a house deposit, the core of the money should stay in high-yield savings, term deposits, or short-duration bond funds rather than volatile assets."
        )
        return {
            "summary": f"You have a clear goal of {goal}. The strongest near-term move is to finish your cash buffer and then invest in a way that matches your {risk} risk tolerance rather than chasing returns.",
            "emergency_fund_title": "Emergency Fund Priority",
            "emergency_fund": (
                f"A 6-month emergency fund is a common baseline because it protects you against job loss, medical bills, or unexpected costs without forcing you to sell investments at the wrong time.\n\n"
                f"1. Monthly expenses = ${monthly_expenses:,.0f}\n"
                f"2. Emergency fund target = ${monthly_expenses:,.0f} × 6 = ${emergency_target:,.0f}\n"
                f"3. Current savings = ${current_savings:,.0f}\n"
                f"4. Gap to fill = ${emergency_target:,.0f} − ${current_savings:,.0f} = ${gap:,.0f}\n"
                f"5. Monthly savings capacity = ${monthly_savings:,.0f}\n"
                f"6. Months to close the gap = ${gap:,.0f} ÷ ${monthly_savings:,.0f} = {months_to_close} months\n\n"
                f"You should prioritise finishing this buffer before putting serious money into growth investments."
            ),
            "strategy_title": "Investment Strategy",
            "strategy": fallback_strategy,
            "allocation_title": "Suggested Allocation",
            "allocation": "70% emergency-fund / cash reserve until fully funded, 20% high-yield savings or short-duration bonds after the buffer is complete, 10% gold ETF only if you want diversification rather than pure return.",
            "risk_title": "Risk Management",
            "risk_note": "Do not rely on gold alone. Keep your deposit or short-term goal money in lower-volatility assets, invest gradually each month, and avoid locking all spare cash into volatile markets before your emergency reserve is complete.",
            "roadmap_title": "90-Day Roadmap",
            "roadmap": [
                "Automate a monthly transfer into your emergency fund.",
                "Keep new short-term goal money in cash or low-volatility instruments.",
                "Add gold only as a small hedge once the emergency fund is on track.",
                "Review progress every month and rebalance only if your goal or timeframe changes.",
            ],
            "emergency_fund_calc": {
                "monthly_expenses": monthly_expenses,
                "emergency_target": emergency_target,
                "current_savings": current_savings,
                "gap": gap,
                "coverage_pct": coverage_pct,
                "monthly_savings": monthly_savings,
                "months_to_close": months_to_close,
            },
        }


# =========================
# HTML FORMATTER
# =========================
def nl_to_html(text: str) -> str:
    escaped = escape(text or "")
    escaped = re.sub(r"^\s*\d+\.\s+(.+)$", r"<li>\1</li>", escaped, flags=re.MULTILINE)
    if "<li>" in escaped:
        escaped = re.sub(r"(<li>.*?</li>)", r"<ol>\1</ol>", escaped, flags=re.DOTALL)
    escaped = escaped.replace("\n\n", "</p><p>").replace("\n", "<br>")
    return f"<p>{escaped}</p>"



def format_currency(value) -> str:
    try:
        return f"${float(value):,.0f}"
    except Exception:
        return "—"



def format_strategy_as_html(strategy: dict) -> str:
    calc = strategy.get("emergency_fund_calc", {})
    coverage = min(max(float(calc.get("coverage_pct", 0) or 0), 0), 100)
    roadmap_items = "".join(f"<li>{escape(str(item))}</li>" for item in strategy.get("roadmap", []))

    return f"""
<div class="strategy-stack">
  <section class="answer-card answer-card--accent">
    <div class="answer-card__label">Summary</div>
    <h3>{escape(strategy.get('summary', 'Your strategy is ready'))}</h3>
  </section>

  <section class="answer-card answer-card--green">
    <div class="answer-card__label">{escape(strategy.get('emergency_fund_title', 'Emergency Fund'))}</div>
    <div class="metric-grid">
      <div class="metric-tile"><span>Monthly Expenses</span><strong>{format_currency(calc.get('monthly_expenses'))}</strong></div>
      <div class="metric-tile"><span>Target (6 months)</span><strong>{format_currency(calc.get('emergency_target'))}</strong></div>
      <div class="metric-tile"><span>Current Savings</span><strong>{format_currency(calc.get('current_savings'))}</strong></div>
      <div class="metric-tile"><span>Gap</span><strong>{format_currency(calc.get('gap'))}</strong></div>
      <div class="metric-tile"><span>Monthly Savings</span><strong>{format_currency(calc.get('monthly_savings'))}</strong></div>
      <div class="metric-tile"><span>Months to Close</span><strong>{calc.get('months_to_close', '—')} mo</strong></div>
    </div>
    <div class="progress-row">
      <div class="progress-bar"><div class="progress-bar__fill" style="width:{coverage}%"></div></div>
      <span>{coverage}% funded</span>
    </div>
    <div class="answer-copy">{nl_to_html(strategy.get('emergency_fund', ''))}</div>
  </section>

  <section class="answer-card answer-card--purple">
    <div class="answer-card__label">{escape(strategy.get('strategy_title', 'Investment Strategy'))}</div>
    <div class="answer-copy">{nl_to_html(strategy.get('strategy', ''))}</div>
  </section>

  <section class="answer-card answer-card--orange">
    <div class="answer-card__label">{escape(strategy.get('allocation_title', 'Allocation'))}</div>
    <div class="answer-copy">{nl_to_html(strategy.get('allocation', ''))}</div>
  </section>

  <section class="answer-card answer-card--cyan">
    <div class="answer-card__label">{escape(strategy.get('risk_title', 'Risk Management'))}</div>
    <div class="answer-copy">{nl_to_html(strategy.get('risk_note', ''))}</div>
  </section>

  <section class="answer-card answer-card--slate">
    <div class="answer-card__label">{escape(strategy.get('roadmap_title', 'Roadmap'))}</div>
    <div class="answer-copy"><ol>{roadmap_items}</ol></div>
  </section>
</div>
"""


# =========================
# ROUTES
# =========================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat")
@app.route("/results")
def legacy_routes():
    return redirect("/")


@app.route("/api/chat", methods=["POST"])
def chat():
    payload = request.get_json() or {}
    message = payload.get("message", "")
    model_choice = payload.get("model", "qwen")

    sid = get_session_id()
    profile = user_profiles[sid]

    if is_greeting(message):
        name_match = re.search(r"(?:my name is|i am|i'm)\s+([A-Za-z]+)", message, re.IGNORECASE)
        name = name_match.group(1).title() if name_match else "there"
        return jsonify({
            "reply": f"Hi {name} 👋 I’m FinBot. I can help with live prices, market news, outlooks, or a personalised strategy. Ask something like ‘gold news’, ‘is it a good time to invest in gold?’, or ‘build me a plan based on my salary and savings.’"
        })
#############
    pending_field = session.get("pending_field")
    if pending_field:
            text = normalize_text(message)

            explicit_exit_phrases = [
                "cancel",
                "stop",
                "reset",
                "start over",
                "exit strategy",
                "stop strategy",
                "switch to market mode",
                "go to market mode",
            ]

            if any(phrase in text for phrase in explicit_exit_phrases):
                session.pop("pending_field", None)
                return jsonify({
                    "reply": "Okay — I’ve paused the personalised strategy flow. You can now ask for market info like 'gold price' or 'gold news'.",
                    "progress": 1
                })

            parsed_value = parse_field_input(message, pending_field)

            if parsed_value is None:
                extracted = extract_user_data(message, profile, model_choice)
                if isinstance(extracted, dict):
                    parsed_value = extracted.get(pending_field)

            if parsed_value is None:
                return jsonify({
                    "reply": f"Please provide a valid answer.\n\n{FIELD_QUESTIONS[pending_field]}",
                    "progress": 2 if pending_field in ["income", "monthly_expenses", "current_savings", "yearly_savings_capacity"] else 3
                })

            profile[pending_field] = parsed_value
            session.pop("pending_field", None)

            missing = get_missing_fields(profile)
            if missing:
                next_field = missing[0]
                session["pending_field"] = next_field

                progress_value = 2 if next_field in [
                    "income",
                    "monthly_expenses",
                    "current_savings",
                    "yearly_savings_capacity"
                ] else 3

                return jsonify({
                    "reply": FIELD_QUESTIONS[next_field],
                    "progress": progress_value
                })

            strategy = generate_strategy(profile, model_choice)
            session["strategy_generated"] = True

            return jsonify({
                "reply": format_strategy_as_html(strategy),
                "type": "strategy",
                "progress": 4,
                "strategy_generated": True
            })          ######

    if is_strategy_request(message):
        extracted = extract_user_data(message, profile, model_choice)
        if extracted:
            profile.update({k: v for k, v in extracted.items() if v not in [None, ""]})

        missing = get_missing_fields(profile)
        if missing:
            next_field = missing[0]
            session["pending_field"] = next_field

            progress_value = 2 if next_field in [
                "income",
                "monthly_expenses",
                "current_savings",
                "yearly_savings_capacity"
            ] else 3

            return jsonify({
                "reply": f"Before I build a personalised strategy, I need a few details.\n\n{FIELD_QUESTIONS[next_field]}",
                "progress": progress_value
            })

        strategy = generate_strategy(profile, model_choice)
        session["strategy_generated"] = True

        return jsonify({
            "reply": format_strategy_as_html(strategy),
            "type": "strategy",
            "progress": 4,
            "strategy_generated": True
        })    

    if should_answer_market_view(message):
        return jsonify({"reply": answer_market_question(message, model_choice)})

    return jsonify({
        "reply": "I can help with live prices, market news, general investment outlooks, or a personalised strategy. Try ‘gold price’, ‘gold news’, ‘is it a good time to invest in gold?’, or ‘build me a strategy’."
    })


@app.route("/reset")
def reset():
    sid = session.get("session_id")
    if sid and sid in user_profiles:
        del user_profiles[sid]
    session.clear()
    return jsonify({"status": "reset"})


if __name__ == "__main__":
    app.run(debug=True)
