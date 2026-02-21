import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

POST_LIMIT = 50
analyzer = SentimentIntensityAnalyzer()

def score(text):
    return analyzer.polarity_scores(text)["compound"]

def get_news_posts(ticker, limit=POST_LIMIT):
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    feed = feedparser.parse(url)
    headlines = [entry.title for entry in feed.entries[:limit]]
    return headlines

def analyze_sentiment(ticker):
    posts = get_news_posts(ticker, POST_LIMIT)
    scores = [score(p) for p in posts if p.strip()]
    if not scores:
        return {
            "Ticker": ticker,
            "Posts": 0,
            "AverageScore": 0,
            "BullishPosts": 0,
            "BearishPosts": 0,
            "Sentiment": "Neutral",
            "Confidence": "0%"
        }

    avg = sum(scores)/len(scores)
    bullish = len([s for s in scores if s > 0.05])
    bearish = len([s for s in scores if s < -0.05])

    if avg > 0.1:
        sentiment = "Bullish"
    elif avg < -0.1:
        sentiment = "Bearish"
    else:
        sentiment = "Neutral"

    confidence = min(100, int(abs(avg)*100 + len(scores)/2))

    return {
        "Ticker": ticker,
        "Posts": len(scores),
        "AverageScore": round(avg,3),
        "BullishPosts": bullish,
        "BearishPosts": bearish,
        "Sentiment": sentiment,
        "Confidence": f"{confidence}%"
    }
