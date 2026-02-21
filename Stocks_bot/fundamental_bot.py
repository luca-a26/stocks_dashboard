import yfinance as yf
import pandas as pd
import time

# ---------------------------------------
# SAFE FIELD EXTRACTOR
# ---------------------------------------
def safe_get(series, keys):
    for k in keys:
        if k in series:
            return series[k]
    return None


# ---------------------------------------
# SINGLE STOCK FUNDAMENTALS
# ---------------------------------------
def analyze_stock(ticker):

    try:
        stock = yf.Ticker(ticker)

        info = stock.info
        bs = stock.balance_sheet
        cf = stock.cashflow

        # -------- Market Cap --------
        market_cap = info.get("marketCap")

        # -------- Balance Sheet --------
        if bs.empty:
            return None

        latest_bs = bs.iloc[:, 0]

        cash = safe_get(latest_bs, [
            "Cash And Cash Equivalents",
            "Cash",
            "CashAndCashEquivalents"
        ])

        debt = safe_get(latest_bs, [
            "Total Debt",
            "TotalDebt"
        ])

        # -------- Cash Burn --------
        burn_rate = None

        if not cf.empty:
            latest_cf = cf.iloc[:, 0]

            operating_cf = safe_get(latest_cf, [
                "Total Cash From Operating Activities",
                "Operating Cash Flow"
            ])

            capex = safe_get(latest_cf, [
                "Capital Expenditures",
                "CapitalExpenditures"
            ])

            if operating_cf is not None and capex is not None:
                burn_rate = operating_cf + capex   # FCF proxy

        return {
            "Ticker": ticker,
            "MarketCap": market_cap,
            "Cash": cash,
            "Debt": debt,
            "CashBurn": burn_rate
        }

    except Exception as e:
        print(f"{ticker} failed: {e}")
        return None


# ---------------------------------------
# MULTI STOCK RUNNER
# ---------------------------------------
def run_yahoo_fundamentals(tickers):

    results = []

    for t in tickers:
        res = analyze_stock(t)
        if res:
            results.append(res)

        time.sleep(1)  # avoid rate limits

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)

    # Derived metrics
    df["NetCash"] = df["Cash"] - df["Debt"]

    return df
