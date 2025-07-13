import logging
from dotenv import load_dotenv
import os
import mysql.connector
import requests
import pytz
from datetime import datetime, time, timedelta, timezone

# --- Load ENV ---
env_path = "/path/to/.env"
load_dotenv(dotenv_path=env_path)

# --- Database Credentials ---
DB_PASS = os.getenv("PASSWORD")
DATABASE = os.getenv("DBNAME_CLIENT")
DB_USER = os.getenv("USERNAME")
DB_HOST = os.getenv("DBHOST", "localhost")

# --- OANDA API Configuration ---
OANDA_KEY = os.getenv("OANDA_DEMO_KEY")
OANDA_ENV = os.getenv("OANDA_ENV", "practice")
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID")
OANDA_URL = "https://api-fxpractice.oanda.com/v3" if OANDA_ENV == "practice" else "https://api-fxtrade.oanda.com/v3"

# --- Constants ---
SYMBOL = 'GBP_JPY'
CANDLE_LIMIT = 100

def get_db_connection():
    """Establishes a connection to the MySQL database."""
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DATABASE
    )

def fetch_oanda_candles(symbol=SYMBOL, granularity="M5", count=CANDLE_LIMIT):
    """Fetches candle data from OANDA."""
    url = f"{OANDA_URL}/instruments/{symbol}/candles"
    headers = {"Authorization": f"Bearer {OANDA_KEY}"}
    params = {"count": count, "granularity": granularity, "price": "M"}
    try:
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        candles = []
        for c in resp.json()["candles"]:
            ts = int(datetime.strptime(c['time'][:19], '%Y-%m-%dT%H:%M:%S').timestamp() * 1000)
            candles.append([
                ts,
                float(c['mid']['o']),
                float(c['mid']['h']),
                float(c['mid']['l']),
                float(c['mid']['c']),
                int(c['volume'])
            ])
        return candles
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching OANDA candles: {e}")
        return []

def fetch_oanda_bid_ask(symbol):
    """Fetches real-time bid/ask pricing data from OANDA."""
    url = f"{OANDA_URL}/accounts/{OANDA_ACCOUNT_ID}/pricing"
    params = {"instruments": symbol}
    headers = {"Authorization": f"Bearer {OANDA_KEY}"}
    try:
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        price = resp.json().get("prices", [])[0]
        bids = [(float(b["price"]), float(b["liquidity"])) for b in price.get("bids", [])]
        asks = [(float(a["price"]), float(a["liquidity"])) for a in price.get("asks", [])]
        return {"bids": bids, "asks": asks}
    except requests.exceptions.RequestException as e:
        logging.error(f"OANDA pricing error: {e}")
        return {"bids": [], "asks": []}
    except (IndexError, KeyError) as e:
        logging.error(f"Error parsing OANDA pricing data: {e}")
        return {"bids": [], "asks": []}


def get_best_bid_ask(orderbook):
    """Extracts the best bid and ask price from an orderbook dictionary."""
    bids = orderbook.get('bids', [])
    asks = orderbook.get('asks', [])
    best_bid = bids[0][0] if bids else None
    best_ask = asks[0][0] if asks else None
    return best_bid, best_ask

def format_duration(delta):
    """Formats a timedelta object into a human-readable string."""
    seconds = int(delta.total_seconds())
    if seconds < 60: return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60: return f"{minutes}m"
    hours = minutes // 60
    return f"{hours}h {minutes % 60}m"

def str_to_utc_dt(s):
    """Converts a string to a UTC datetime object."""
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=pytz.UTC)
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.UTC)

def get_active_or_recent_session(now_utc=None):
    """Determines the current or most recent major trading session."""
    if not now_utc:
        now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)

    sessions = [
        {"name": "Tokyo", "start": time(0, 0), "end": time(8, 0), "major": True},
        {"name": "London", "start": time(7, 0), "end": time(15, 0), "major": True},
        {"name": "New York", "start": time(12, 0), "end": time(21, 0), "major": True},
    ]
    for sess in sessions:
        start_dt = now_utc.replace(hour=sess["start"].hour, minute=sess["start"].minute, second=0, microsecond=0)
        if now_utc.time() < sess["start"]:
            start_dt -= timedelta(days=1)
        
        end_dt = start_dt + timedelta(hours=(sess["end"].hour - sess["start"].hour) % 24)
        if start_dt <= now_utc < end_dt:
            mins_since_open = int((now_utc - start_dt).total_seconds() // 60)
            duration_str = format_duration(now_utc - start_dt)
            msg = f"{sess['name']} session opened {duration_str} ago"
            return sess["name"], start_dt, msg, sess['major'], mins_since_open

    return None, None, "No major session active", False, None


def run_session_orb(symbol="GBP_JPY", timeframe="15m", orb_minutes=15):
    """Calculates and reports on the opening range breakout for the current session."""
    messages = []
    now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)
    session, session_open_dt, session_msg, is_major, mins_since_open = get_active_or_recent_session(now_utc)
    
    messages.append(f"[{session or 'N/A'}] {session_msg}")

    if not session_open_dt or not is_major:
        return messages
        
    if mins_since_open is not None and mins_since_open < 30:
        messages.append(f"Caution: First {mins_since_open}m of {session}. High risk of chop/fakeout.")

    orb_end_dt = session_open_dt + timedelta(minutes=orb_minutes)
    
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            table = f"forex_candles_{timeframe}"
            query = f"SELECT * FROM `{table}` WHERE symbol = %s AND `timestamp` >= %s ORDER BY `timestamp` ASC"
            cur.execute(query, (symbol, session_open_dt.strftime("%Y-%m-%d %H:%M:%S")))
            candles = cur.fetchall()

    if not candles:
        messages.append(f"No {timeframe} candles found since session open.")
        return messages

    orb_candles = [c for c in candles if str_to_utc_dt(c['timestamp']) < orb_end_dt]
    if not orb_candles:
        messages.append(f"No candles found within the {orb_minutes}-min ORB window.")
        return messages
        
    orb_high = max(c['high'] for c in orb_candles)
    orb_low = min(c['low'] for c in orb_candles)
    messages.append(f"ORB High={orb_high}, Low={orb_low}")

    after_orb = [c for c in candles if str_to_utc_dt(c['timestamp']) >= orb_end_dt]
    if after_orb:
        first_breakout_candle = after_orb[0]
        if first_breakout_candle['high'] > orb_high:
            messages.append(f"Breakout UP occurred at {first_breakout_candle['timestamp']}.")
        elif first_breakout_candle['low'] < orb_low:
            messages.append(f"Breakout DOWN occurred at {first_breakout_candle['timestamp']}.")
    
    return messages


def get_todays_news():
    """Fetches today's financial news from the database."""
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            today_str = datetime.utcnow().strftime('%Y-%m-%d')
            cur.execute("SELECT title, date, sentiment FROM gbpjpy_news WHERE DATE(date) = %s", (today_str,))
            news = cur.fetchall()
    
    now = datetime.now(timezone.utc)
    for n in news:
        post_time = n['date'].replace(tzinfo=timezone.utc)
        hours_ago = round((now - post_time).total_seconds() / 3600, 1)
        n['hours_ago'] = hours_ago
        n['date'] = post_time.strftime('%Y-%m-%d %H:%M')
    return news

def find_last_swing_high_low(candles, window=3):
    """Finds the most recent swing high and low in a series of candles."""
    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    n = len(candles)
    for i in range(n - window - 1, window - 1, -1):
        is_high = all(highs[i] > highs[j] for j in range(i - window, i + window + 1) if j != i)
        if is_high:
            return highs[i], i
    return None, None

def detect_all_fvgs(candles, lookback=50):
    """Detects all Fair Value Gaps (FVG) in the recent candle history."""
    fvgs = []
    for i in range(len(candles) - 2, max(0, len(candles) - lookback - 1), -1):
        prev_high, prev_low = candles[i - 1][2], candles[i - 1][3]
        next_high, next_low = candles[i + 1][2], candles[i + 1][3]
        # Bullish FVG
        if prev_high < next_low:
            fvgs.append({'type': 'bullish', 'top': next_low, 'bottom': prev_high})
        # Bearish FVG
        if prev_low > next_high:
            fvgs.append({'type': 'bearish', 'top': prev_low, 'bottom': next_high})
    return fvgs

def find_sr_liquidity_zones(candles, lookback=50, swing_window=3):
    """Identifies key support, resistance, and liquidity zones from candle data."""
    recent_candles = candles[-lookback:]
    swing_high, swing_high_idx = find_last_swing_high_low(recent_candles, window=swing_window)
    fvgs = detect_all_fvgs(recent_candles, lookback=lookback)
    return {
        'local_high': max(c[2] for c in recent_candles),
        'local_low': min(c[3] for c in recent_candles),
        'swing_high': swing_high,
        'last_close': recent_candles[-1][4],
        'fvgs': fvgs
    }

def get_all_tf_sr_liquidity():
    """Aggregates support/resistance data across multiple timeframes."""
    results = {}
    for tf in ['4h', '1h', '15m']:
        granularity = {'4h': 'H4', '1h': 'H1', '15m': 'M15'}[tf]
        candles = fetch_oanda_candles(SYMBOL, granularity=granularity, count=100)
        if candles:
            results[tf] = find_sr_liquidity_zones(candles)
    return results
