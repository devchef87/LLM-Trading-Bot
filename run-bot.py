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

# Your DB Connection, storing decisions etc..
from db_query import ...

# import our indicators
from indicators import (
    run_session_orb,
    get_todays_news,
    get_all_tf_sr_liquidity,
    get_best_bid_ask,
    fetch_oanda_bid_ask,
    get_db_connection
)

# --- Logging ---
log_file_path = "grok-4.log"
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
logging.basicConfig(filename=log_file_path, level=logging.INFO, format="%(asctime)s - %(message)s")

# --- Load ENV ---
env_path = "/path/to/.env"
load_dotenv(dotenv_path=env_path)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
XAI_API_KEY = os.getenv("GROK_API_KEY")

# --- Constants ---
PROMPT_PATH = "prompt.json" # This is the prompt we will inject indicator data into and feed to Grok
MODEL_NAME = "Grok-4"
SYMBOL = "GBP_JPY"

# I trade Oanda, update to whatever exchange you use
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID_PREDATOR")
OANDA_KEY = os.getenv("OANDA_DEMO_KEY")
OANDA_ENV = os.getenv("OANDA_ENV", "practice")
OANDA_URL = "https://api-fxpractice.oanda.com/v3" if OANDA_ENV == "practice" else "https://api-fxtrade.oanda.com/v3"

# Load in json prompt
def load_prompt_file(filename):
    with open(filename, 'r') as f:
        data = json.load(f)
        return data['prompt']
        
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


# Connect to the database and get the open trade to pass each cycle, so AI has the situational awareness
def get_open_trade():
    """Checks for an open paper trade for the current model."""
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT * FROM paper_trades WHERE status = 'OPEN' AND model = %s ORDER BY entry_time DESC LIMIT 1",
                (MODEL_NAME,)
            )
            return cur.fetchone()

# Connect to the database and feed trades back in for memory  / learning
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

# Clean up and prepare the data for open and previous trades
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

# run analysis with our prompt injected
def ai_analysis(prompt):

    if not XAI_API_KEY:
        logging.error("GROK_API_KEY not found in environment variables.")
        return None

    try:
        client = Client(api_key=XAI_API_KEY)
        chat = client.chat.create(model="grok-4-latest", temperature=0.7)
        chat.append(system("You are a disciplined, data-driven forex trading AI. Respond ONLY in JSON."))
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

        # this is where we inject our data into the json prompt
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

        #Review the full prompt making sure data is correct
        logging.info(f"Raw Promp: {prompt}")

        # Here you parse and decide what to do with the decision, connect to an exchange, log to DB etc..
        ai_decision = ai_analysis(prompt)
        logging.info(f"AI Decision: {ai_decision}")

    except Exception as e:
        logging.error(f"Error in main(): {e}", exc_info=True)


if __name__ == "__main__":
    main()
