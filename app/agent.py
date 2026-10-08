# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import json
import os
from google.cloud import firestore

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.genai import types

from a2ui.schema.manager import A2uiSchemaManager
from a2ui.basic_catalog.provider import BasicCatalog
from .a2ui_utils import a2ui_callback


MODEL = "gemini-3.8-flash"
PROJECT_ID = "qwiklabs-gcp-03-99d8dc84aabc"


def _get_db():
    return firestore.Client(project=PROJECT_ID)


def get_portfolio_holdings() -> str:
    """Retrieves all current paper stock positions and portfolio holdings from Firestore.

    Returns:
        A formatted summary of current holdings, including ticker, shares, average price, current price, and unrealized profit/loss.
    """
    db = _get_db()
    docs = db.collection("portfolio_holdings").stream()
    holdings = []
    total_val = 0.0

    for doc in docs:
        data = doc.to_dict()
        ticker = data.get("ticker", doc.id)
        shares = data.get("shares", 0)
        avg_price = data.get("avg_price", 0.0)
        curr_price = data.get("current_price", avg_price)
        val = shares * curr_price
        total_val += val
        pnl = (curr_price - avg_price) * shares
        pnl_pct = ((curr_price - avg_price) / avg_price * 100) if avg_price else 0.0
        holdings.append(
            f"- {ticker} ({data.get('name', '')}): {shares} shares @ avg ${avg_price:.2f} | Current: ${curr_price:.2f} | Value: ${val:,.2f} | P&L: ${pnl:+,.2f} ({pnl_pct:+.2f}%) [{data.get('notes', '')}]"
        )

    if not holdings:
        return "Portfolio currently has no open stock holdings."

    return f"Active Holdings (Total Value: ${total_val:,.2f}):\n" + "\n".join(holdings)


def get_account_summary() -> str:
    """Fetches the paper trading account cash balance and benchmark goal.

    Returns:
        Information on cash balance, total capital, and active benchmark target.
    """
    db = _get_db()
    doc = db.collection("portfolio_meta").document("account").get()
    if not doc.exists:
        return "No account metadata found."
    data = doc.to_dict()
    cash = data.get("cash_balance", 0.0)
    initial = data.get("initial_capital", 100000.0)
    benchmark = data.get("benchmark", "SPY")
    profile = data.get("risk_profile", "Growth")
    return (
        f"Paper Trading Account Summary:\n"
        f"- Cash Available: ${cash:,.2f}\n"
        f"- Initial Capital: ${initial:,.2f}\n"
        f"- Target Benchmark to Beat: {benchmark}\n"
        f"- Strategy / Risk Profile: {profile}"
    )


def execute_paper_trade(
    ticker: str,
    action: str,
    shares: int,
    price: float,
    rationale: str = "",
    user_confirmed: bool = False,
) -> str:
    """Executes a simulated (paper) trade to buy or sell stocks in the portfolio and updates Firestore.

    Args:
        ticker: The stock ticker symbol (e.g., 'GOOGL', 'NVDA', 'AAPL').
        action: Either 'BUY' or 'SELL'.
        shares: The number of shares to trade (must be a positive integer).
        price: The execution price per share in USD.
        rationale: The strategic thesis or rationale for executing this trade to generate alpha.
        user_confirmed: Set to True ONLY if the user has explicitly reviewed and confirmed/approved this specific trade after being prompted.

    Returns:
        A confirmation message, or an approval request if trade value exceeds 10% of total portfolio value.
    """
    ticker = ticker.upper().strip()
    action = action.upper().strip()
    if action not in ["BUY", "SELL"]:
        return "Invalid action. Must be 'BUY' or 'SELL'."
    if shares <= 0:
        return "Shares must be greater than 0."
    if price <= 0:
        return "Price must be greater than 0."

    db = _get_db()
    trade_value = shares * price

    account_ref = db.collection("portfolio_meta").document("account")
    account_doc = account_ref.get()
    cash = account_doc.to_dict().get("cash_balance", 0.0) if account_doc.exists else 50000.0

    # Calculate total portfolio value (cash + all active holdings)
    total_stock_value = 0.0
    for doc in db.collection("portfolio_holdings").stream():
        d = doc.to_dict()
        s = d.get("shares", 0)
        p = d.get("current_price", d.get("avg_price", 0.0))
        total_stock_value += s * p
    total_portfolio_value = cash + total_stock_value

    # 10% Portfolio Threshold Approval Guardrail
    if total_portfolio_value > 0:
        trade_pct = (trade_value / total_portfolio_value) * 100
        if trade_pct > 10.0 and not user_confirmed:
            return (
                f"APPROVAL REQUIRED: This proposed {action} order for {shares} shares of {ticker} at ${price:.2f} "
                f"is valued at ${trade_value:,.2f}, which is {trade_pct:.1f}% of your total portfolio (${total_portfolio_value:,.2f}). "
                f"Because this exceeds the 10% safety threshold, please ask the user for explicit approval before proceeding. "
                f"Do not call execute_paper_trade again until the user confirms."
            )

    holding_ref = db.collection("portfolio_holdings").document(ticker)
    holding_doc = holding_ref.get()
    current_holding = holding_doc.to_dict() if holding_doc.exists else {}
    existing_shares = current_holding.get("shares", 0)
    existing_avg = current_holding.get("avg_price", price)

    if action == "BUY":
        if cash < trade_value:
            return f"Order rejected: Insufficient cash balance (${cash:,.2f}) for ${trade_value:,.2f} order."
        new_shares = existing_shares + shares
        new_avg = ((existing_shares * existing_avg) + trade_value) / new_shares
        new_cash = cash - trade_value

        holding_ref.set({
            "ticker": ticker,
            "name": current_holding.get("name", f"{ticker} Inc."),
            "shares": new_shares,
            "avg_price": round(new_avg, 2),
            "current_price": price,
            "sector": current_holding.get("sector", "Equities"),
            "notes": rationale or current_holding.get("notes", "Paper position"),
            "updated_at": firestore.SERVER_TIMESTAMP,
        })
        account_ref.update({"cash_balance": round(new_cash, 2)})
        return (
            f"Successfully executed BUY for {shares} shares of {ticker} at ${price:.2f} (Total: ${trade_value:,.2f}).\n"
            f"New Position: {new_shares} shares @ avg ${new_avg:.2f}.\n"
            f"Remaining Cash: ${new_cash:,.2f}."
        )
    else:  # SELL
        if existing_shares < shares:
            return f"Order rejected: Cannot sell {shares} shares; only holding {existing_shares} shares of {ticker}."
        new_shares = existing_shares - shares
        new_cash = cash + trade_value

        if new_shares == 0:
            holding_ref.delete()
        else:
            holding_ref.update({
                "shares": new_shares,
                "current_price": price,
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
        account_ref.update({"cash_balance": round(new_cash, 2)})
        return (
            f"Successfully executed SELL for {shares} shares of {ticker} at ${price:.2f} (Proceeds: ${trade_value:,.2f}).\n"
            f"Remaining Position: {new_shares} shares.\n"
            f"New Cash Balance: ${new_cash:,.2f}."
        )


def fetch_live_stock_quote(ticker: str) -> str:
    """Fetches real-time market quote data for any publicly traded stock or ETF symbol.

    Args:
        ticker: The stock or ETF ticker symbol (e.g. 'AAPL', 'NVDA', 'SPY', 'GOOGL', 'TSLA').

    Returns:
        A summary of the current price, day high/low, previous close, and percentage change.
    """
    import json
    import urllib.request

    symbol = ticker.upper().strip()
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            results = data.get("chart", {}).get("result")
            if not results:
                return f"No market data found for ticker '{symbol}'."
            meta = results[0].get("meta", {})
            curr_price = meta.get("regularMarketPrice")
            prev_close = meta.get("chartPreviousClose", curr_price)
            day_high = meta.get("regularMarketDayHigh", curr_price)
            day_low = meta.get("regularMarketDayLow", curr_price)
            currency = meta.get("currency", "USD")

            if curr_price is None:
                return f"Could not retrieve real-time price for {symbol}."

            change = curr_price - prev_close if prev_close else 0.0
            change_pct = (change / prev_close * 100) if prev_close else 0.0

            return (
                f"Live Market Quote for {symbol}:\n"
                f"- Current Price: ${curr_price:,.2f} {currency}\n"
                f"- Daily Change: ${change:+,.2f} ({change_pct:+.2f}%)\n"
                f"- Day Range: ${day_low:,.2f} - ${day_high:,.2f}\n"
                f"- Previous Close: ${prev_close:,.2f}"
            )
    except Exception as e:
        return f"Error fetching quote for {symbol}: {str(e)}"


def fetch_live_market_news(query_or_ticker: str) -> str:
    """Fetches the latest real-time market and financial news headlines for a stock, company, or market sector.

    Args:
        query_or_ticker: Stock ticker or search topic (e.g., 'AAPL', 'NVDA', 'semiconductors', 'Federal Reserve').

    Returns:
        A list of recent news articles with titles, publishers, publish dates, and links.
    """
    import json
    import urllib.parse
    import urllib.request

    topic = query_or_ticker.strip()
    encoded = urllib.parse.quote(topic)
    url = f"https://query1.finance.yahoo.com/v1/finance/search?q={encoded}&newsCount=5"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            news_items = data.get("news", [])
            if not news_items:
                return f"No recent market news found for '{topic}'."

            formatted = [f"Latest Market News for '{topic}':"]
            for idx, item in enumerate(news_items[:5], 1):
                title = item.get("title", "No Title")
                publisher = item.get("publisher", "Unknown Publisher")
                link = item.get("link", "")
                formatted.append(f"{idx}. [{publisher}] {title}\n   Link: {link}")

            return "\n\n".join(formatted)
    except Exception as e:
        return f"Error retrieving market news for '{topic}': {str(e)}"


BUCKET_NAME = "alpha-hedge-storage-3661"


async def generate_trading_visual(prompt: str, tool_context: ToolContext) -> str:
    """Generates an image for a trading milestone, portfolio breakdown, or technical pattern, saves it as an artifact, and uploads to GCS.

    Args:
        prompt: A detailed description of the trading visual to generate (e.g. 'A futuristic golden bull trophy badge representing beating the market alpha').

    Returns:
        The public HTTPS URL of the uploaded image on Cloud Storage.
    """
    import uuid
    from google import genai
    from google.cloud import storage

    # Generate image using gemini-3.1-flash-lite-image in the global location
    client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")
    response = client.models.generate_content(
        model="gemini-3.1-flash-lite-image",
        contents=prompt,
    )

    image_bytes = None
    mime_type = "image/jpeg"

    for candidate in response.candidates:
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if part.inline_data and part.inline_data.data:
                    image_bytes = part.inline_data.data
                    mime_type = part.inline_data.mime_type or "image/jpeg"
                    break
        if image_bytes:
            break

    if not image_bytes:
        return "Failed to generate image: No image data returned from model."

    filename = f"visual_{uuid.uuid4().hex[:8]}.jpg"

    # 1. Save artifact to ToolContext so it shows in Playground's Artifacts panel
    artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    await tool_context.save_artifact(filename=filename, artifact=artifact_part)

    # 2. Upload same bytes directly to Cloud Storage bucket without local file write
    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(filename)
    blob.upload_from_string(image_bytes, content_type=mime_type)

    public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"
    return f"Image generated successfully! Public URL: {public_url}"


# Configure Agent Engine Sandbox Code Executor
_deployment_meta_path = os.path.join(os.path.dirname(__file__), "..", "deployment_metadata.json")
_agent_engine_id = None
if os.path.exists(_deployment_meta_path):
    try:
        with open(_deployment_meta_path, "r") as f:
            _meta = json.load(f)
            _agent_engine_id = _meta.get("remote_agent_runtime_id")
    except Exception:
        pass

sandbox_code_executor = (
    AgentEngineSandboxCodeExecutor(agent_engine_resource_name=_agent_engine_id)
    if _agent_engine_id
    else AgentEngineSandboxCodeExecutor()
)

# Build A2UI System Prompt using A2uiSchemaManager (version 0.8) & Basic Catalog
schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are AlphaHedge, an autonomous AI Paper Stock Trading and Portfolio Management Agent. "
        "Your mission is to help the user maximize simulated profits and beat market benchmark indices (e.g. S&P 500 / SPY). "
        "You have direct access to: "
        "1. Live market quotes (`fetch_live_stock_quote`) to check real-time stock prices. "
        "2. Real-time market news (`fetch_live_market_news`) to analyze sentiment, catalysts, and breaking headlines. "
        "3. Portfolio Firestore database (`get_portfolio_holdings`, `get_account_summary`) to inspect positions and cash. "
        "4. Paper order execution (`execute_paper_trade`) to execute simulated buy/sell trades with clear analytical rationale. "
        "5. Image generation (`generate_trading_visual`) to create visual badges, charts, or milestones. "
        "6. Sandbox Python code execution to safely run mathematical modeling, quantitative calculations, and data analysis. "
        "When executing or automating trades: "
        "- For trades whose total value is <= 10% of the portfolio, execute them automatically. "
        "- CRITICAL SAFETY RULE: If a proposed trade exceeds 10% of total portfolio value (or if `execute_paper_trade` returns an APPROVAL REQUIRED message), "
        "STOP immediately, present the trade details (ticker, action, shares, price, trade value, and % of portfolio) to the user, and ask for their explicit confirmation. "
        "- Only call `execute_paper_trade` with `user_confirmed=True` AFTER the user has explicitly confirmed their approval in their message."
    ),
    workflow_description="Analyze market data, portfolio state, and trading requests, and return structured A2UI cards for visual representation.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        "{\"Image\": {\"url\": {\"literalString\": \"https://...\"}}}. Never point an "
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="alpha_hedge",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=instruction,
    tools=[
        fetch_live_stock_quote,
        fetch_live_market_news,
        get_portfolio_holdings,
        get_account_summary,
        execute_paper_trade,
        generate_trading_visual,
    ],
    code_executor=sandbox_code_executor,
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
