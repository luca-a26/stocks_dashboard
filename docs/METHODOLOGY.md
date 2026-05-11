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

On-demand scored ticker details are cached separately under:

```text
storage/cache/scores/
```

The score cache uses `SCORE_CACHE_TTL_HOURS`, defaulting to 6 hours. Fresh cached scores can be used in the default top-100 ranking. Stale cached scores are labelled with `score_status = stale` if they are displayed after a failed refresh.

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

## Hybrid Rare-Earth Score

The current dashboard score is a rare-earth-specific hybrid composite on a 0-10 scale:

```text
composite_score =
  technical_asset_score * 0.55
  + commercial_financial_score * 0.25
  + strategic_supply_chain_score * 0.20
```

All component scores and the final composite are capped between 0 and 10. Missing values are not fabricated. They are scored neutrally where appropriate, recorded in `missing_data_fields`, and reflected in `scoring_confidence`.

### Technical Asset Score

Technical quality is the largest component. It is a weighted score:

```text
resource_scale_grade       -> 18%
magnet_basket_quality      -> 18%
mineralogy_quality         -> 18%
metallurgy_derisking       -> 23%
resource_confidence        -> 13%
impurity_penalty_profile   -> 10%
```

The model rewards defined resources, TREO grade, resource scale, contained TREO/NdPr, mine-life evidence, NdPr-rich baskets, HREE/Dy/Tb exposure, understood mineralogy, metallurgical testwork, recovery data, concentrate grades, flowsheet validation, pilot work, resource confidence, and clean impurity profiles.

It records missing fields such as:

```text
defined_resource
treo_grade_pct
resource_tonnage_mt
contained_treo_tonnes
contained_ndpr_tonnes
ndpr_pct_of_treo
mineralogy
metallurgical_testwork
recovery_pct
concentrate_grade_pct
resource_category
impurity_profile
```

### Commercial / Financial Score

The old revenue/debt logic has been adapted into a broader commercial score:

```text
revenue_quality                 -> 20%
debt_balance_sheet              -> 20%
cash_runway_or_funding_risk     -> 20%
study_economics                 -> 20%
offtake_funding_validation      -> 20%
```

Important changes from the earlier model:

- Pre-revenue developers are not heavily penalised for having no revenue.
- REE-relevant revenue scores better than unrelated revenue.
- Missing revenue or debt is neutral but logged as missing evidence.
- Debt is scored as balance-sheet risk, with zero/low debt rewarded and high debt penalised.
- Cash runway, funding risk, study economics, government support, strategic investors, offtake, funding packages, and development route validation can improve the score when those fields exist.

### Strategic Supply Chain Score

Strategic value is scored as:

```text
jurisdiction_quality             -> 25%
processing_depth                 -> 35%
ex_china_supply_chain_value      -> 25%
esg_permitting_social_licence    -> 15%
```

Processing depth is intentionally important. Exploration-only assets score lower, concentrate routes score moderately, carbonate/hydroxide routes score higher, separated oxides score high, and metals/alloys/magnets/recycling score very high.

Processor, recycler, and magnet businesses can score well through strategic supply-chain relevance even if they do not own a mineral deposit.

### Stage Gates

Stage gates cap weakly evidenced mining projects so early-stage names cannot score like advanced projects without resource and metallurgy evidence:

```text
no defined resource                    -> max composite score 5.5
no metallurgical testwork              -> max composite score 6.0
no recovery data                       -> max composite score 6.5
no scoping study / PEA / PFS / DFS      -> max composite score 7.0
no funding/offtake/development route   -> max composite score 8.0
```

The dashboard exposes applied gates in `applied_stage_gates`, for example:

```text
No defined resource (cap 5.5)
No metallurgical testwork (cap 6.0)
```

Downstream processors/recyclers/magnet companies are not automatically capped by mining-resource gates when the missing resource is not central to their business model.

### Confidence

`scoring_confidence` / `data_quality_score` is a 0-10 coverage score based on data completeness, freshness, and presence of core fields. Market cap and 52-week range remain confidence/coverage evidence, not direct asset-quality boosts.

## Preliminary Metadata Score

The large ticker universe is searchable at startup without downloading full fundamentals. Companies that only have cheap metadata receive a low-confidence preliminary score aligned to the hybrid model.

Metadata-only scoring starts around 4.0 and applies modest boosts for:

```text
priority
producer/developer status
processor/recycler/magnet role
HREE / Dy / Tb exposure
NdPr / rare-earth exposure
large market-cap tier
```

Metadata-only companies are capped at 5.5 unless verified technical fields exist. They are clearly labelled as `metadata_only` and should be treated as discovery triage, not full analysis.

## Score Status

The ranked table includes score status so full and preliminary scores are not silently mixed:

```text
full          -> detailed market, financial, and technical data are available
partial       -> some detailed data exists, but key financial or technical fields are missing
metadata_only -> only lightweight universe metadata is available
stale         -> cached detailed data is outside the TTL and live refresh failed
```

The displayed `Score` column uses `composite_score` for sorting. `Full Score`, `Prelim Score`, `Tech Score`, `Commercial Score`, `Strategic Score`, and `Confidence` remain separate columns.

## Rating Labels

The table converts numeric scores into simple rating labels:

```text
score >= 7.5    -> High-quality / advanced
score >= 6.0    -> Strong watchlist
score >= 4.5    -> Developing opportunity
score >= 3.0    -> Early / speculative
score < 3.0     -> Low confidence / insufficient evidence
```

These are dashboard triage labels, not buy/sell/hold recommendations.

## Explainability Output

Each scored company exposes:

- `composite_score`
- `technical_asset_score`
- `commercial_financial_score`
- `strategic_supply_chain_score`
- `scoring_confidence`
- `score_status`
- `rating_label`
- `score_breakdown`
- `missing_data_fields`
- `applied_stage_gates`
- `reason_codes`
- `explanation_bullets`

Reason codes are intentionally short for dashboard display, such as `Strong NdPr exposure`, `Defined JORC/NI 43-101 resource`, `Metallurgical recovery data unavailable`, `Concentrate-only processing route`, `HREE exposure present`, `Debt data unavailable`, `No published study economics`, and `Advanced downstream processing capability`.

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
