import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

from investiny import search_assets, historical_data

from data.utils import ensure_storage_path, get_logger, load_config, load_tickers

CONFIG = load_config()
CACHE_DIR = ensure_storage_path("storage/cache/prices")


def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker}.csv"


def _find_investing_id(query: str, exchange: str = None):
    """
    Search Investing.com assets for a given ticker/name.
    Returns the first matching investing_id.
    """
    try:
        results = search_assets(
            query=query,
            limit=3,
            type="Stock",
            exchange=exchange if exchange else ""
        )
    except Exception as e:
        raise RuntimeError(f"Investiny search failed for '{query}': {e}")

    if not results:
        raise RuntimeError(f"No Investing.com ID found for '{query}'")

    return int(results[0]["ticker"])


def fetch_price_history(ticker_code: str, force_refresh: bool = False) -> pd.DataFrame:
    """
    Fetch OHLCV history for ticker_code via investiny.
    Tries a search first to get investing_id, then fetches historical_data.
    """

    tickers = load_tickers()
    if ticker_code not in tickers:
        raise ValueError(f"Unknown ticker code: {ticker_code}")

    cache_file = _cache_path(ticker_code)
    today = datetime.today().date()

    # Use cache if fresh
    if cache_file.exists() and not force_refresh:
        cached = pd.read_csv(cache_file, parse_dates=["Date"], index_col="Date")
        if cached.index.max().date() >= today - timedelta(days=1):
            return cached

    # Search Investing.com IDs
    query = tickers[ticker_code].get("investiny", ticker_code)
    investing_id = _find_investing_id(query)

    # Define lookback window
    lookback_days = CONFIG["general"]["lookback_days"]
    from_date = (today - timedelta(days=lookback_days)).strftime("%m/%d/%Y")
    to_date = today.strftime("%m/%d/%Y")

    try:
        raw = historical_data(
            investing_id=investing_id,
            from_date=from_date,
            to_date=to_date
        )
    except Exception as e:
        raise RuntimeError(f"Investiny historical_data failed for {ticker_code}: {e}")

    if not raw:
        raise RuntimeError(f"No data returned for {ticker_code} from investiny")

    # Convert to DataFrame
    df = pd.DataFrame(raw)

    # Normalize column names
    df.rename(columns={
        "date": "Date",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume"
    }, inplace=True)

    # Convert to datetime index
    df["Date"] = pd.to_datetime(df["Date"])
    df.set_index("Date", inplace=True)
    df.sort_index(inplace=True)

    # Drop rows with missing volume or OHLC
    df = df.dropna(subset=["open", "high", "low", "close"])

    # Save cache
    df.to_csv(cache_file)

    return df

def normalize_price_df(df):

    if df is None or df.empty:
        return None

    # flatten MultiIndex columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # lowercase columns
    df.columns = [c.lower() for c in df.columns]

    # ensure numeric
    for col in ["open","high","low","close","volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # drop bad rows
    if "close" in df.columns:
        df = df.dropna(subset=["close"])

    return df

def fetch_all_prices(force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    """
    Fetch price history for all configured tickers.
    Returns dict[ticker_code] = DataFrame
    """
    out = {}
    for code in load_tickers().keys():
        try:
            out[code] = fetch_price_history(code, force_refresh)
        except Exception as e:
            get_logger(__name__).warning("%s: %s", code, e)
    return out
