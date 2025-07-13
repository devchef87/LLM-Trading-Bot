import logging
from dotenv import load_dotenv
import os
import json
import re
from datetime import datetime
from decimal import Decimal
import sys
import requests
from xai_sdk import Client, user, system

# Add the parent directory to the module search path
sys.path.append(os.path.abspath("/var/www/forex-trader/helpers"))

from db_query import (
    handle_paper_position,
    load_prompt_file,
    save_ai_memory,
    get_db_connection
)

from indicators import (
    run_session_orb,
    get_todays_news,
    get_all_tf_sr_liquidity,
    get_best_bid_ask,
    fetch_oanda_bid_ask
)

# --- Logging ---
log_file_path = "/var/www/forex-trader/logs/grok-4.log"
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
logging.basicConfig(filename=log_file_path, level=logging.INFO, format="%(asctime)s - %(message)s")

# --- Load ENV ---
env_path = "/var/www/html/sec/.env"
load_dotenv(dotenv_path=env_path)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID_PREDATOR")
OANDA_KEY = os.getenv("OANDA_DEMO_KEY")
OANDA_ENV = os.getenv("OANDA_ENV", "practice")
XAI_API_KEY = os.getenv("GROK_API_KEY")

# --- Constants ---
PROMPT_PATH = "/var/www/forex-trader/prompts/predator.json"
MODEL_NAME = "Grok-4"
SYMBOL = "GBP_JPY"
OANDA_URL = "https://api-fxpractice.oanda.com/v3" if OANDA_ENV == "practice" else "https://api-fxtrade.oanda.com/v3"

# --- Suppress noisy logging ---
for logger_name in ["httpx", "openai", "httpcore"]:
    logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_pricing(symbol, oanda_account_id):
    """Fetches the current bid/ask price for a symbol from OANDA."""
    url = f"{OANDA_URL}/accounts/{oanda_account_id}/pricing?instruments={symbol}"
    headers = {"Authorization": f"Bearer {OANDA_KEY}"}
    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        prices = r.json()["prices"][0]
        bid = float(prices["bids"][0]["price"])
        ask = float(prices["asks"][0]["price"])
        return (bid + ask) / 2
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching OANDA pricing: {e}")
        return None


def get_open_trade():
    """Checks for an open paper trade for the current model."""
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT * FROM paper_trades WHERE status = 'OPEN' AND model = %s ORDER BY entry_time DESC LIMIT 1",
                (MODEL_NAME,)
            )
            return cur.fetchone()


def get_last_closed_trades(model=MODEL_NAME, n=10):
    """Retrieves the last n closed trades for a given model."""
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(
                """
                SELECT direction, entry_price, exit_price, profit_loss, entry_time, exit_time, ai_reason
                FROM paper_trades
                WHERE status = 'CLOSED' AND model = %s
                ORDER BY exit_time DESC LIMIT %s
                """,
                (model, n)
            )
            trades = []
            for row in cur.fetchall():
                row['entry_time'] = str(row['entry_time'])
                row['exit_time'] = str(row['exit_time'])
                trades.append(row)
            return trades


def prepare_trade_for_json(trade_row):
    """Prepares a trade row for inclusion in the LLM prompt."""
    if not trade_row:
        return None
    # Ensure all datetime and Decimal objects are JSON serializable
    for key, value in trade_row.items():
        if isinstance(value, datetime):
            trade_row[key] = value.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(value, Decimal):
            trade_row[key] = float(value)
    return trade_row


def ai_analysis(prompt):
    """Sends a prompt to the Grok API and returns the JSON response."""
    if not XAI_API_KEY:
        logging.error("GROK_API_KEY not found in environment variables.")
        return None

    try:
        client = Client(api_key=XAI_API_KEY)
        chat = client.chat.create(model="grok-4-latest", temperature=0.7)
        chat.append(system("You are a disciplined, data-driven crypto trading AI. Respond ONLY in JSON."))
        chat.append(user(prompt))

        response = chat.sample()
        content = response.content.strip()

        # Clean up potential markdown formatting
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()

        return json.loads(content)

    except json.JSONDecodeError as e:
        logging.error(f"Grok: Failed to parse JSON: {e}, content: {content}")
    except Exception as e:
        logging.error(f"Grok API error: {e}")
    return None


def main():
    """Main execution function."""
    try:
        if get_open_trade():
            logging.info("Trade already open. Skipping new AI prompt.")
            return

        open_trade_json = "null"
        last_closed_trades = get_last_closed_trades()
        last_closed_trades_json = json.dumps(last_closed_trades) if last_closed_trades else "[]"

        prompt_template = load_prompt_file(PROMPT_PATH)
        todays_news = get_todays_news()
        get_zones = get_all_tf_sr_liquidity()
        current_price = get_pricing(SYMBOL, OANDA_ACCOUNT_ID)
        ai_prompt_snippet = "\n".join(run_session_orb())
        orderbook = fetch_oanda_bid_ask(SYMBOL)
        bid, ask = get_best_bid_ask(orderbook)

        prompt = prompt_template.format(
            current_trade_json=open_trade_json,
            last_closed_trade_json=last_closed_trades_json,
            timeframe='1h',
            todays_news=todays_news,
            current_price=current_price,
            get_zones=get_zones,
            session_info=ai_prompt_snippet,
            bid=bid,
            ask=ask,
        )

        ai_decision = ai_analysis(prompt)
        logging.info(f"AI Decision: {ai_decision}")

        if ai_decision:
            handle_paper_position(ai_decision, MODEL_NAME, OANDA_ACCOUNT_ID, symbol=SYMBOL)
            save_ai_memory(MODEL_NAME, "1h", ai_decision)
        else:
            logging.error("AI decision was None, skipping trade record.")

    except Exception as e:
        logging.error(f"Error in main(): {e}", exc_info=True)


if __name__ == "__main__":
    main()
