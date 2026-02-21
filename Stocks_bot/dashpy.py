import time
import pandas as pd
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
from main import run
import dash
from dash import Dash, dcc, html, Input, Output, State
import dash_bootstrap_components as dbc
from dotenv import load_dotenv
import os
from google import genai
import dash_ag_grid as dag
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*Timestamp.utcnow.*")


load_dotenv()

api_key = os.getenv("GEMINI_KEY")

client = genai.Client(api_key=api_key)

# Cache for LLM
llm_cache = {}
CACHE_TTL = 300  # 1 hour

ta_df, fund_df, sentiment_df = run()

# ---------------- DASH APP ----------------
external_stylesheets = [dbc.themes.CERULEAN]
app = Dash(__name__, external_stylesheets=external_stylesheets)

app.layout = dbc.Container([
    dbc.Row([
        html.Div('Stock Dashboard', className="text-primary text-center fs-3")
    ]),

    dbc.Tabs([

        # ---------- SUMMARY TAB ----------
        dbc.Tab(label="Summary", tab_id="summary", children=[
            dbc.Row([
                dbc.Col([
                    dcc.RadioItems(
                        id="summary-interval",
                        options=[
                            {"label":"Daily (6mo)", "value":"1d"},
                            {"label":"1 Hour (30d)", "value":"1h"}
                        ],
                        value="1d",
                        inline=True,
                    )
                ], width=3)
            ], className="mb-2"),

            dcc.Interval(id="live-update", interval=30*1000, n_intervals=0),

            dbc.Row([
                dbc.Col([
                    dcc.Dropdown(
                        id="summary-ticker",
                        options=[{"label": t, "value": str(t).strip()} for t in ta_df["Ticker"].unique()],
                        value=ta_df["Ticker"].iloc[0],
                        clearable=False
                    )
                ], width=4)
            ], className="mb-3"),

            dbc.Row([dbc.Col([dcc.Graph(id="price-chart")])])
        ]),

        # ---------- TECHNICAL TAB ----------
        dbc.Tab(label="Technical", children=[
            dbc.Row([
                dbc.RadioItems(
                    options=[{"label": x, "value": x} for x in ['Price','DailyHigh','TrendScore']],
                    value='Price',
                    inline=True,
                    id='tech-radio'
                )
            ]),
            dbc.Row([
                dbc.Col(
                    dag.AgGrid(
                        rowData=ta_df.to_dict("records"),
                        columnDefs=[{"field": i} for i in ta_df.columns]
                    ),
                    width=6
                ),
                dbc.Col(dcc.Graph(id='tech-graph'), width=6)
            ])
        ]),

        # ---------- FUNDAMENTAL TAB ----------
        dbc.Tab(label="Sentiment", children=[
            dbc.Row([
                dbc.RadioItems(
                    options=[{"label": x, "value": x} for x in fund_df.columns if x!="Ticker"],
                    value=fund_df.columns[1],
                    inline=True,
                    id='fund-radio'
                )
            ]),
            dbc.Row([
                dbc.Col(
                    dag.AgGrid(
                        rowData=fund_df.to_dict("records"),
                        columnDefs=[{"field": i} for i in fund_df.columns]
                    ),
                    width=6
                ),
                dbc.Col(dcc.Graph(id='fund-graph'), width=6)
            ])
        ]),

        # ---------- SENTIMENT TAB ----------
        dbc.Tab(label="Fundamental", children=[
            dbc.Row([
                dbc.RadioItems(
                    options=[{"label": x, "value": x} for x in sentiment_df.columns if x!="Ticker"],
                    value=sentiment_df.columns[1],
                    inline=True,
                    id='sent-radio'
                )
            ]),
            dbc.Row([
                dbc.Col(
                    dag.AgGrid(
                        rowData=sentiment_df.to_dict("records"),
                        columnDefs=[{"field": i} for i in sentiment_df.columns]
                    ),
                    width=6
                ),
                dbc.Col(dcc.Graph(id='sent-graph'), width=6)
            ])
        ]),

        # ---------- AI LLM TAB ----------
        dbc.Tab(label="AI Research", children=[
            dbc.Row([
                dbc.Col([
                    dcc.Textarea(
                        id="llm-query",
                        value="Provide key metrics, risks, and trends for mid-cap rare earth mining companies.",
                        style={"width":"100%","height":"80px"}
                    ),
                    dbc.Button("Run Query", id="llm-button", n_clicks=0, color="primary", className="mt-2")
                ], width=12)
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    dcc.Loading(
                        id="llm-loading",
                        type="circle",
                        children=html.Div(id="llm-text-output", style={"whiteSpace":"pre-wrap", "border":"1px solid #ccc", "padding":"10px", "minHeight":"100px"})
                    )
                ], width=12)
            ])
        ])
    ])
], fluid=True)

# Global conversation history
messages_history = {}

def query_llm_to_text(user_prompt: str, ticker: str=None) -> str:
    global messages_history

    if not user_prompt.strip():
        return ""

    # create ticker memory
    if ticker not in messages_history:
        messages_history[ticker] = [
            {"role": "system", "content": "You are a professional financial analyst."}
        ]

    history = messages_history[ticker]

    cache_key = f"{ticker}:{user_prompt}"
    if cache_key in llm_cache:
        return llm_cache[cache_key]

    # build structured prompt
    conversation_text = "\n".join(
        [f"{m['role']}: {m['content']}" for m in history]
    )

    prompt = f"""
Ticker: {ticker}

Conversation:
{conversation_text}

User Question:
{user_prompt}

Provide concise financial analysis.
"""

    history.append({"role":"user","content":user_prompt})

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt
        )
        reply = response.text.strip()

    except Exception as e:
        return f"LLM Error: {str(e)}"

    history.append({"role":"assistant","content":reply})
    llm_cache[cache_key] = reply

    return reply


# ---------------- PRICE CHART ----------------
@dash.callback(
    Output('price-chart','figure'),
    Input('summary-ticker','value'),
    Input('summary-interval','value'),
    Input('live-update','n_intervals')
)
def update_price_chart(ticker, interval, _):
    ticker = ticker.strip().upper()
    period_map = {"1d":"6mo","1h":"30d"}
    df = yf.download(ticker, period=period_map[interval], interval=interval, progress=False)

    if df.empty:
        return px.line(title=f"No data for {ticker}")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    current_price = df["Close"].iloc[-1]
    prev = df["Close"].iloc[-2] if len(df) > 1 else current_price
    pct = ((current_price - prev)/prev)*100
    color = "green" if pct>=0 else "red"

    fig = go.Figure(data=[go.Candlestick(
        x=df.index,
        open=df["Open"],
        high=df["High"],
        low=df["Low"],
        close=df["Close"]
    )])
    rangebreaks = [dict(bounds=["sat","mon"])]

    if interval == "1h":
        rangebreaks.append(dict(bounds=[16, 9.5], pattern="hour"))

    fig.update_layout(
        template="plotly_white",
        margin=dict(l=10,r=10,t=40,b=10),
        title=f"<span style='color:{color}'>{ticker} ({interval}) — {current_price:.2f} ({pct:+.2f}%)</span>",
        xaxis=dict(rangebreaks=rangebreaks)
    )

    return fig

# ---------------- TECH / FUND / SENTIMENT ----------------
@dash.callback(Output('tech-graph','figure'), Input('tech-radio','value'))
def update_tech(col): return px.histogram(ta_df, x='Ticker', y=col, histfunc='avg')

@dash.callback(Output('fund-graph','figure'), Input('fund-radio','value'))
def update_fund(col): return px.histogram(fund_df, x='Ticker', y=col, histfunc='avg')

@dash.callback(Output('sent-graph','figure'), Input('sent-radio','value'))
def update_sent(col): return px.histogram(sentiment_df, x='Ticker', y=col, histfunc='avg')

# ---------------- LLM CALLBACK ----------------
@app.callback(
    Output("llm-text-output", "children"),
    Input("llm-button", "n_clicks"),
    State("llm-query", "value"),
    State("summary-ticker", "value"),
    prevent_initial_call=True
)
def run_llm_text(n_clicks, query, ticker):
    return query_llm_to_text(query, ticker)


# ---------------- RUN APP ----------------
if __name__ == '__main__':
        app.run(debug=True)
