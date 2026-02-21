import pandas as pd
import yfinance as yf
import time

TICKERS = ["PRE.L", "SML.L", "ALK.L", "REE.L", "TIN.L"]


# ---------- SIGNAL ----------
def signal(price, ma):
    if price > ma:
        return "Bullish"
    elif price < ma:
        return "Bearish"
    return "Neutral"


# ---------- TREND SCORE ----------
def trend_strength(price, sma20, sma50, sma200):
    score = 0

    if price > sma20: score += 1
    if price > sma50: score += 1
    if price > sma200: score += 2

    if sma20 > sma50 > sma200:
        score += 2
    elif sma20 < sma50 < sma200:
        score -= 2

    return score


# ---------- FETCH DATA ----------
def get_data(ticker):

    stock = yf.Ticker(ticker)

    # price info
    info = stock.info

    # historical candles
    hist = stock.history(period="1y")

    if hist.empty:
        return None

    # moving averages
    hist["SMA20"] = hist["Close"].rolling(20).mean()
    hist["SMA50"] = hist["Close"].rolling(50).mean()
    hist["SMA200"] = hist["Close"].rolling(200).mean()

    latest = hist.iloc[-1]

    return {
        "price": info.get("currentPrice"),
        "high": info.get("dayHigh"),
        "low": info.get("dayLow"),
        "sma20": latest["SMA20"],
        "sma50": latest["SMA50"],
        "sma200": latest["SMA200"]
    }


# ---------- ANALYSIS ----------
def analyze_ticker(ticker):

    data = get_data(ticker)

    if not data:
        print(f"{ticker} failed")
        return None

    price = data["price"]

    short = signal(price, data["sma20"])
    medium = signal(price, data["sma50"])
    long = signal(price, data["sma200"])

    trend = trend_strength(
        price,
        data["sma20"],
        data["sma50"],
        data["sma200"]
    )

    return {
        "Ticker": ticker,
        "Price": round(price,2),
        "DailyHigh": data["high"],
        "DailyLow": data["low"],
        "ShortTerm": short,
        "MediumTerm": medium,
        "LongTerm": long,
        "TrendScore": trend
    }


# ---------- RUN ----------
def run_technical(tickers=TICKERS):

    results = []

    for t in tickers:
        r = analyze_ticker(t)
        if r:
            results.append(r)

        time.sleep(1)  # avoid Yahoo rate limits

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df = df.sort_values("TrendScore", ascending=False)

    return df