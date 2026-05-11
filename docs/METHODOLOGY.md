# Dashboard Methodology

This document describes the current methodology used by the Strategic Metals Dashboard for data collection, scoring, ratings, display calculations, charts, and manual discovery tracking.

The dashboard is an informational research tool. Scores are not investment advice and should be treated as a structured triage layer rather than a valuation model.

## Data Sources

### LSE Instrument Data

Primary live market data comes from the London Stock Exchange gateway:

```text
https://api.londonstockexchange.com/api/gw/lse/instruments/alldata/{TICKER}
```

The dashboard uses this endpoint for:

- Ticker / TIDM
- Issuer name
- ISIN
- Currency
- Market, such as `AIM` or `MAINMARKET`
- Segment, such as `ASQ1`, `SSQ3`, or `SET3`
- Market capitalisation
- Last price
- Bid and offer
- Volume
- Turnover
- 52-week low and high
- Listing admission date
- Issuer code, used for LSE tearsheet lookup

### LSE Tearsheet PDF

Where available, a company tearsheet PDF is downloaded from:

```text
https://api.londonstockexchange.com/api/gw/lse/download/{ISSUER_CODE}/tearsheet
```

The first page of the PDF is parsed for key statistics:

- Employees
- Revenue LFY (M)
- EPS Diluted LFY
- Market Value (M)
- Shares Outstanding LFY (000)
- Book Value Per Share
- EBITDA Margin %
- Net Margin %
- Long-Term Debt / Capital %
- Dividends and Yield TTM
- Payout Ratio TTM %
- 60-Day Average Volume (000)
- 52-Week High & Low
- Price / 52-Week High & Low

The dashboard currently uses:

- `Revenue LFY`
- `Long-Term Debt / Capital %`
- `Shares Outstanding LFY`
- selected margin/book-value fields for future expansion

### FTSE Analytics PDF Fallback

Some stocks do not expose the standard LSE tearsheet. In those cases, the dashboard attempts a fallback:

```text
https://api.londonstockexchange.com/api/gw/lse/download/{TICKER}/ftse-analytics
```

Current fallback fields:

- Net Debt / Equity
- Price / Sales, if a numeric value is available
- Price / Book, if a numeric value is available

This is why some companies show a debt metric as `net debt/equity` rather than `LT debt/cap`.

## Caching

LSE data is cached under:

```text
storage/cache/lse/
```

Cache time-to-live:

```text
6 hours
```

If a live request fails and a cache file exists, the dashboard uses the stale cache and logs a warning. If no cache exists, the failure is surfaced through the data-loading path.

## Unit Normalisation

### Revenue LFY

The LSE tearsheet reports:

```text
Revenue LFY (M)
```

The dashboard converts this to absolute currency units:

```text
revenue_lfy = revenue_lfy_m * 1,000,000
```

Example:

```text
5.0 on the tearsheet -> 5,000,000
```

### Shares Outstanding

The LSE tearsheet reports:

```text
Shares Outstanding LFY (000)
```

The dashboard converts this to absolute shares:

```text
shares_outstanding_lfy = shares_outstanding_lfy_000 * 1,000
```

Example:

```text
339,248 on the tearsheet -> 339,248,000 shares
```

### Market Capitalisation

Market capitalisation comes from the LSE instrument JSON as `marketcapitalization`.

The dashboard does not recalculate market cap from price and shares. The LSE value is used directly.

### Debt Metric

Debt metric priority:

1. Use `Long-Term Debt / Capital %` from the LSE tearsheet when available.
2. Otherwise use `Net Debt / Equity` from the FTSE analytics fallback when available.
3. Otherwise display `n/a`.

The table label states which basis is used:

```text
0.0% LT debt/cap
0.1% net debt/equity
```

## Score Calculation

Each company receives a conservative 0-10 fundamental score.

### Base Score

Every company starts at:

```text
score = 5.0
```

This is a neutral baseline. The current model is not designed to aggressively rank early-stage companies that lack complete financial data.

### Market Cap Availability

If LSE market capitalisation is available:

```text
score adjustment = 0
driver = "LSE market cap available"
```

Market cap availability is currently a confidence/coverage driver, not a scoring boost.

### Revenue LFY Adjustment

Revenue is scored as follows:

```text
if revenue_lfy is None:
    adjustment = 0
    driver = "Revenue LFY unavailable"
elif revenue_lfy > 20,000,000:
    adjustment = +1.0
    driver = "Revenue-generating (>20M LFY)"
elif revenue_lfy > 0:
    adjustment = +0.5
    driver = "Revenue-generating"
else:
    adjustment = -1.0
    driver = "Pre-revenue / no LFY revenue"
```

Interpretation:

- Companies with meaningful reported revenue receive a positive adjustment.
- Companies with small but non-zero revenue receive a smaller positive adjustment.
- Pre-revenue companies are penalised modestly.
- Missing revenue does not change the score, because absence can reflect missing tearsheet coverage rather than business quality.

### Debt Adjustment

The dashboard first chooses a debt metric:

```text
debt_metric = long_term_debt_to_capital_pct if available
else net_debt_to_equity_pct if available
else None
```

Then applies:

```text
if debt_metric is None:
    adjustment = 0
    driver = "Debt metric unavailable"
elif debt_metric == 0:
    adjustment = +1.0
    driver = "No LSE-reported debt burden"
elif debt_metric <= 25:
    adjustment = +0.5
    driver = "Moderate LSE-reported debt burden"
elif debt_metric >= 50:
    adjustment = -1.5
    driver = "High LSE-reported debt burden"
else:
    adjustment = 0
```

Interpretation:

- Zero debt burden is rewarded.
- Low/moderate debt burden is rewarded modestly.
- High debt burden is penalised.
- Debt metrics between 25 and 50 receive no adjustment in the current model.

### 52-Week Range Availability

If both 52-week low and high are available:

```text
score adjustment = 0
driver = "52-week trading range available"
```

This is currently a coverage/diagnostic driver, not a scoring input.

### Score Bounds

After all adjustments:

```text
score = min(max(score, 0), 10)
score = round(score, 2)
```

The score cannot go below 0 or above 10.

## Rating Labels

The table converts numeric scores into simple rating labels:

```text
score >= 7      -> High conviction
score >= 5      -> Constructive
score >= 3      -> Watch
score < 3       -> Review
```

These are dashboard triage labels, not buy/sell/hold recommendations.

## Composite Score

The current composite score is identical to the fundamental score:

```text
composite_score = fundamental_score
```

Earlier technical and sentiment surfaces were removed. The architecture still allows future score components to be added, but they are not currently active.

Future composite scoring could use a weighted model such as:

```text
composite = (fundamental_score * w1)
          + (project_score * w2)
          + (catalyst_score * w3)
          + (supply_chain_score * w4)
```

No such weighted composite is currently used.

## Display Calculations

### Money Formatting

Money-like values are formatted with suffixes:

```text
>= 1,000,000,000,000 -> T
>= 1,000,000,000     -> B
>= 1,000,000         -> M
>= 1,000             -> K
otherwise            -> comma-formatted integer
```

Examples:

```text
360,585,531 -> 360.6M
5,000,000   -> 5.0M
0           -> 0
None        -> n/a
```

### Number Formatting

Share counts and volume use:

```text
>= 1,000,000,000 -> B
>= 1,000,000     -> M
>= 1,000         -> K
otherwise        -> comma-formatted integer
```

### Price Formatting

Last price is formatted as:

```text
{last_price} {currency}
```

Example:

```text
101.2 GBX
```

### 52-Week Range

The dashboard uses LSE JSON values:

```text
52W Range = "{fifty_two_week_low} - {fifty_two_week_high}"
```

Example:

```text
26.6 - 184.5
```

## Discovery Pipeline Methodology

Discovery data is manually maintained in:

```text
config/ree_pipeline.yaml
```

This avoids storing third-party credentials or automating gated research access.

### Project Pipeline Fields

Current fields:

- Ticker
- Company
- Exchange
- Project
- Commodity Focus
- REE Class
- Role
- Country
- Stage
- Drill Results
- Historic Mine
- Source Confidence
- Priority
- Notes

These fields are not currently scored mathematically. They are intended for screening, filtering, and research workflow management.

### Supply Chain Ranking Fields

Current fields:

- Segment
- Entity
- Role
- Ranking
- Jurisdiction
- Exposure
- Source
- Status
- Notes

This table is designed to receive manual or compliant exports from specialist sources such as Rare Earth Exchanges. Current placeholder rows track required imports for:

- Heavy Rare Earths
- Light Rare Earths
- Processors
- Magnet makers

### Catalyst Tracker Fields

Current fields:

- Ticker
- Company
- Catalyst
- Category
- Timing
- Status
- Impact
- Source
- Owner
- Notes

These are workflow fields, not calculated financial factors.

## Chart Methodology

Dashboard charts are simple counts from the manual discovery data.

### Count Charts

For a selected field:

```text
count_by(field) = number of rows for each distinct field value
```

Examples:

- Projects by stage
- Catalysts by category
- Supply-chain items by segment

### Donut Charts

Donut charts use the same count methodology but display proportions:

```text
share = field_count / total_rows
```

Examples:

- Exposure split by REE Class
- Catalyst impact mix
- Supply-chain status mix

## Known Limitations

- The current score is intentionally simple and financial-data-led.
- Market cap, 52-week range, exchange, and segment affect visibility but not the numeric score.
- Project quality, grade, tonnage, metallurgy, jurisdiction, funding runway, and management quality are not yet scored.
- LSE tearsheets are not available for every company.
- Some fallback metrics use different debt definitions, so the table labels the debt basis.
- Discovery pipeline fields are manually curated and should be reviewed before formal use.
- Rare Earth Exchanges data should be imported manually or through a compliant workflow; credentials must not be stored in the repo.

## Recommended Next Methodology Upgrade

A more complete model should add separate scored modules:

1. Project quality score
2. Supply-chain strategic value score
3. Catalyst score
4. Jurisdiction/permitting risk score
5. Funding runway score
6. Valuation vs maturity score

The dashboard can then move from:

```text
composite_score = fundamental_score
```

to a weighted multi-factor composite.
