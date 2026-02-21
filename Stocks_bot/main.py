from TA import run_technical, TICKERS
from sentiment import analyze_sentiment
from fundamental_bot import run_yahoo_fundamentals
import pandas as pd
from functools import reduce

def safe_add_ticker(df, default_name="Ticker"):
    """Ensure DataFrame has a Ticker column."""
    if df.empty:
        return df
    if 'Ticker' not in df.columns:
        df = df.rename(columns={df.columns[0]: 'Ticker'})
    return df

def run():
    # ---------- TECHNICAL ----------
    print("\nRunning Technical Analysis...")
    ta_df = run_technical(TICKERS)
    ta_df = safe_add_ticker(ta_df)

    # ---------- SENTIMENT ----------
    print("\nRunning Sentiment Analysis...")
    sentiment_results = []
    for t in TICKERS:
        try:
            sentiment_results.append(analyze_sentiment(t))
        except Exception as e:
            print(f"{t} failed sentiment analysis: {e}")

    sentiment_df = pd.DataFrame(sentiment_results)
    sentiment_df = safe_add_ticker(sentiment_df)

    # ---------- FUNDAMENTALS ----------
    print("\nRunning Fundamental Analysis...")
    try:
        fund_df = run_yahoo_fundamentals(TICKERS)
        #fund_df = safe_add_ticker(fund_df)
    except Exception as e:
        print(f"Fundamental analysis failed: {e}")
        fund_df = pd.DataFrame()

    # ---------- MERGE DATA ----------
    dfs_to_merge = [df for df in [ta_df, sentiment_df, fund_df] if not df.empty]

    if not dfs_to_merge:
        print("\nNo data available from any source.")
        return

    print("\nCOMBINED TECHNICAL + SENTIMENT + FUNDAMENTAL REPORT")
    print("-"*100)
    print(ta_df.to_string(index=False))
    print(sentiment_df.to_string(index=False))
    print(fund_df.to_string(index=False))

    return ta_df, sentiment_df, fund_df

if __name__ == "__main__":
    run()
