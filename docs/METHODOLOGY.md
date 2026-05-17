# Dashboard Methodology

This document describes the current methodology used by the Strategic Metals Dashboard for data collection, scoring, ratings, display calculations, charts, and manual discovery tracking.

The dashboard is an informational research tool. Scores are not investment advice and should be treated as a structured triage layer rather than a valuation model.

## Data Sources

### Canonical Market Snapshot

The dashboard now loads a committed market snapshot before attempting fragile live fallbacks:

```text
data/company_market_snapshot.csv
data/company_market_snapshot.json
```

The snapshot is the first stable source for broad-universe market cap and shares in issue. It records:

- Ticker and company name
- Market cap display value, native numeric value, and currency
- Shares in issue
- Snapshot status
- Canonical source URL
- Snapshot date
- Notes
- Optional last price, price currency/unit, volume, and 52-week range

Snapshot statuses are explicit and dashboard-safe:

```text
reported
computed
manual
found_lse_share_page
found_via_non_constituent_search
found_suspended_security
not_available_gdr_zero_shares_on_source
not_applicable_preference_share_no_market_cap
not_found
stale
conflicting
```

The snapshot is refreshed by GitHub Actions every three hours through:

```text
python -m scripts.refresh_company_market_snapshot
```

The workflow fetches London South East per-company pages using canonical source URLs, optionally falls back to LSE/Yahoo providers for missing rows, writes CSV/JSON outputs, and uploads a coverage audit artifact. Runtime dashboard loading uses the snapshot first and only uses live fetchers for missing or stale rows when explicitly enabled.

### LSE Instrument Data

Detailed live market data comes from the London Stock Exchange gateway:

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

### LSE Website Page Fallback

If the LSE gateway or tearsheet leaves important fields empty or inconsistent, the dashboard now checks the public LSE stock pages directly:

```text
https://www.londonstockexchange.com/stock/{TICKER}/{company-slug}/company-page
https://www.londonstockexchange.com/stock/{TICKER}/{company-slug}/our-story
https://www.londonstockexchange.com/stock/{TICKER}/{company-slug}/fundamentals
```

This fallback is used for public page fields such as:

- Instrument / issuer market cap
- Last price and price currency
- Volume
- 52-week low and high
- Market
- Market segment
- Trading service
- ISIN
- Country of share register or incorporation
- FTSE sector/subsector

If the API value and public-page market cap disagree materially, the public LSE page value is used and the row records a correction note in `Data Notes`.

### London South East Share-Page Fallback

The broad Industrial Metals universe comes from London South East sector pages. The sector list itself provides useful lightweight price and volume fields, but not always market cap. To prevent metadata-only rows from showing avoidable blanks, the dashboard can enrich each London South East sector constituent from:

```text
https://www.lse.co.uk/SharePrice.html?shareprice={TICKER}&share={company-slug}
```

This page is parsed for basic market fields:

- Market cap
- Last price
- Currency
- Volume
- Shares in issue
- Year high and low
- Trade count
- Issue country

Runtime live startup enrichment is now disabled by default because the canonical snapshot carries the stable broad-universe market fields. Enable live startup fallback only for deliberate refresh/debug sessions:

```powershell
$env:ENABLE_LIVE_MARKET_REFRESH=true
```

Detailed financial refreshes still use the same fallback chain.

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

### Yahoo Finance Fallback

When LSE data coverage is below the dashboard target threshold, the detailed loader tries a cached Yahoo Finance fallback using the `{TICKER}.L` symbol convention for London-listed equities.

Fallback fields can include:

- Market capitalisation
- Last price
- Volume
- 52-week low and high
- Shares outstanding
- Total revenue, used as a revenue fallback when LSE LFY revenue is unavailable
- Debt/equity
- Price/sales and price/book

Fallback-filled rows are labelled in `Source` and `Data Notes`. The dashboard does not hide fallback provenance: if revenue is supplied by the fallback it is scored conservatively and marked as estimated.

### RNS Technical Evidence

The rare-earth score now has a dedicated technical-evidence layer for the fields that matter most to deposit quality but are usually absent from market-data providers:

```text
mineralogy
metallurgical_testwork
recovery_pct
concentrate_grade_pct
resource_category
study_stage
treo_grade_pct
resource_tonnage_mt
contained_treo_tonnes
contained_ndpr_tonnes
ndpr_pct_of_treo
impurity_profile
thorium_ppm
uranium_ppm
capex
opex
processing_depth
```

Tracked evidence lives in:

```text
config/rns_technical_evidence.csv
```

Automated refresh output, when enabled, is written to:

```text
data/rns_technical_evidence.csv
storage/audit/rns_technical_evidence_audit.json
```

The refresh command is:

```powershell
python -m scripts.refresh_rns_technical_evidence
```

The scheduled workflow uses `data/company_market_snapshot.csv` as the input universe so the technical-evidence pass covers the broad dashboard company list, not only the curated watchlist.

The parser reads recent RNS article pages, extracts technical fields from announcement text, records the source title/date/URL, and feeds those fields into the same scoring inputs used by the hybrid methodology. Direct London Stock Exchange RNS URLs are parsed through the official article JSON payload. Broad ticker discovery uses London South East's static `/rns/{ticker}/` pages as a fallback because the current LSE analysis pages are client-rendered shells. Relevant project/documentation RNS candidates are kept even when structured field extraction is incomplete. This lets the dashboard show `RNS found - review needed` instead of silently implying no technical documentation exists.

Live RNS fetching is not required at dashboard startup. By default, the dashboard reads tracked/configured evidence and the latest generated snapshot if present. Live refresh can be enabled for deliberate update sessions with:

```powershell
$env:ENABLE_RNS_TECHNICAL_REFRESH="true"
```

RNS-derived evidence is visible in the comparison table through `Mineralogy`, `Recovery`, `Study Stage`, `Resource Confidence`, `Impurity Profile`, `Technical Status`, and `Technical Source`. The company overview modal also shows RNS technical evidence and links to source announcements where available.

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
Expired cached scores that are merely reused for fast startup preserve their analytical status (`full` or `partial`) and carry cache age separately as `score_cache_state = stale`. This prevents cache age from being mistaken for evidence completeness.

Yahoo Finance fallback payloads are cached under:

```text
storage/cache/yahoo/
```

The fallback cache also uses a 6-hour TTL.

The field-owned financial layer includes parser-version-aware cache-state helpers for provider caches. Negative cache entries can expire separately from successful fundamentals so a previous `not_found` result does not permanently suppress future successful lookups. Existing raw LSE/London South East/Yahoo caches remain compatible; parsed financial records now carry provenance and quality flags so stale or conflicting fields can be audited.

The committed market snapshot is governed by:

```text
MARKET_SNAPSHOT_PATH=data/company_market_snapshot.csv
MARKET_SNAPSHOT_MAX_AGE_HOURS=6
MARKET_SNAPSHOT_REQUIRED_COVERAGE=0.95
ENABLE_LIVE_MARKET_REFRESH=false
ENABLE_MARKET_REFRESH_ACTION=true
```

Snapshot refresh audit output is written to `storage/audit/` and uploaded by the workflow rather than committed.

## Unit Normalisation

## Field-Owned Financial Pipeline

The dashboard now treats financial data as field-owned rather than source-owned. Each key field is selected independently from the best available source, carries provenance, and can be audited before display.

Canonical identity fields are built from config and fetched metadata where available:

```text
company_id
display_name
legal_name
primary_ticker
exchange
mic
isin
sedol
figi
share_class_figi
quote_currency
reporting_currency
lse_issuer_code
lse_slug
yahoo_symbol
company_stage
manual_review_status
```

The current field set includes:

```text
last_price
price_currency
price_date
volume
market_cap
shares_outstanding
revenue
revenue_status
total_debt
debt_to_equity
price_to_sales
price_to_book
fifty_two_week_high
fifty_two_week_low
isin
market
segment
sector
subsector
country
```

Each field has:

```text
value
source
source_rank
as_of_date / fetched_at
status
confidence
notes
currency / unit where relevant
source_url where relevant
```

### Market Cap Computation

Market cap priority is:

```text
manual override
computed price x shares outstanding
company market snapshot
LSE official/API/PDF
Yahoo or structured fallback
London South East live share page
explicit not_found or not_applicable status
```

Market cap is computed when valid price and share count are available:

```text
market_cap = normalized_last_price * shares_outstanding
```

UK pence prices are normalised first:

```text
247.5 GBp -> 2.475 GBP
```

The dashboard keeps original price, price unit, normalised price, and normalised currency metadata. If a vendor-reported market cap exists, the dashboard uses that reported/source value and keeps `normalised price x shares outstanding` only as a cross-check. If the cross-check differs by more than 15%, `market_cap_vendor_conflict` is added to `data_quality_flags`; the source market cap still remains the displayed value unless a high-confidence manual override replaces it. Computed market cap is used only when no usable source market cap is available.

### Revenue Status

Revenue is no longer treated as a simple number-or-missing field. It has a status:

```text
reported
confirmed_zero
pre_revenue_confirmed
likely_pre_revenue_unconfirmed
not_found
stale
conflicting
manual
```

Display-safe coverage counts `reported`, `confirmed_zero`, `pre_revenue_confirmed`, and `manual` as populated. It does not count `likely_pre_revenue_unconfirmed`, `not_found`, `stale`, or `conflicting` as strict populated revenue.

### Manual Overrides

Manual financial corrections live in:

```text
config/company_financial_overrides.csv
```

Columns:

```text
company_id,ticker,field,value,currency,unit,as_of_date,source_url,source_name,confidence,notes,last_verified
```

Overrides are applied after automated sources. They fill missing fields by default. To override an already populated automated field, use high confidence, currently `0.95` or above, or include `force` in the notes. Overrides are visible in `Data Notes` and add `manual_override_used` to quality flags.

### Coverage Audit

Before display, the pipeline can produce a coverage audit with:

```text
Universe count
Price coverage
Shares outstanding coverage
Market cap coverage
Revenue status coverage
Volume coverage
52-week high/low coverage
Strict full coverage
Display-safe coverage
List of companies failing coverage by field
Pass/fail against the 95% display-safe target
```

The dashboard logs this audit during default ranked-stock loading.

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
3. Otherwise use Yahoo Finance debt/equity fallback when available.
4. Otherwise display `n/a`.

The table label states which basis is used:

```text
0.0% LT debt/cap
0.1% net debt/equity
```

### Data Coverage

The comparison table includes `Data Coverage`, which measures how many of the key financial fields are populated for a row:

```text
market cap
last price
volume
52-week range
revenue
debt metric
shares outstanding
```

When detailed LSE coverage is below 95%, the loader attempts fallback enrichment. Some junior or shell companies may still remain below target because public revenue, debt, or shares data genuinely is not available from the configured sources.

Rows should not display silent blank cells. If a value remains unresolved after configured fallbacks, the table shows an explicit label such as `Not found`, `Not found after fallback`, `Not loaded`, or `Unclassified`.

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

### Workbook Benchmark Layer

The hybrid score is enhanced by the same benchmark framework used in the rare-earth deposit valuation workbook. This layer is still on a 0-10 scale, but its category design follows the workbook:

```text
resource_deposit_quality          -> 25%
economics_valuation               -> 25%
revenue_downstream_integration    -> 20%
production_development            -> 15%
strategic_criticality             -> 15%
```

The benchmark layer uses fields when they are available, including total mineral deposit value, ore reserve value, mineral resource value, TREO grade, NdPr content, DyTb content, NPV 5/8/10, deposit value, annual mining/processing/separation/magnet/other revenue, current or 2026 ore production, planned 2027/2028 production, life of mine, sector coverage, HREE exposure, and magnet supply-chain exposure.

Numeric factors are compared against median sector benchmarks when supplied. The dashboard uses the same capped median-relative method as the workbook, converted to the 0-10 dashboard scale:

```text
score_100 = MIN(100, MAX(0, 50 + 50 * (project_value - benchmark_median) / ABS(benchmark_median)))
score_10  = score_100 / 10
```

If a project value exists but no benchmark exists, the field is treated as modest evidence rather than invented precision. If the field is missing, it is excluded from the weighted category and added to `missing_data_fields`.

The layer exposes:

- `benchmark_score`
- `benchmark_breakdown`
- `data_completeness_score`
- `confidence_level`
- `suggested_peer_group`
- `top_positive_drivers`
- `top_negative_drivers`

When benchmark evidence exists, it blends into the three main hybrid components rather than replacing them:

- Resource/deposit quality and production visibility enhance `technical_asset_score`.
- Economics/valuation and downstream revenue integration enhance `commercial_financial_score`.
- Strategic criticality enhances `strategic_supply_chain_score`.

This keeps the original 55/25/20 rare-earth composite intact while making deposit quality, project economics, production visibility, and downstream integration more visible in the dashboard score.

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

`scoring_confidence` / `data_quality_score` is a 0-10 coverage score based on data completeness, freshness, and presence of core fields. The workbook layer also exposes `data_completeness_score` and a simple `confidence_level` of High, Medium, or Low. Market cap and 52-week range remain confidence/coverage evidence, not direct asset-quality boosts.

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

The displayed `Score` column uses `composite_score` for sorting. `Full Score`, `Prelim Score`, `Tech Score`, `Commercial Score`, `Strategic Score`, `Benchmark Score`, `Confidence`, `Confidence Level`, and `Peer Group` remain separate columns.

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

## Relative Peer Comparison Popup

The company-card popup adds a relative comparison layer without changing the main hybrid score. It is designed for small peer groups where users want to compare up to four companies directly.

Rows in the main scoreboard are clickable. The clicked company becomes the anchor card, and the side tray can add or remove peers. The relative scorecard uses five equally weighted criteria, each scored from 1 to 5:

- Minerals, grade & deposit quality.
- Commodity price outlook.
- Jurisdiction & political stability.
- Dilution & warrant overhang.
- Application & strategic relevance.

These scores are relative to the selected peer group, not absolute global rankings. A `5` means best of the currently selected companies on that criterion. The dilution criterion is intentionally inverse: higher means lower dilution risk.

Automatic relative scores are derived from existing dashboard outputs where possible:

- Grade/deposit quality uses technical asset score and resource/deposit benchmark evidence.
- Commodity price outlook uses explicit override data when supplied; otherwise it defaults to neutral `3/5` with a missing-evidence note.
- Jurisdiction uses the strategic jurisdiction component when available, otherwise the strategic score as a proxy.
- Dilution risk uses the cash runway/funding-risk commercial component when available, otherwise a commercial-score proxy.
- Application relevance uses processing depth, ex-China supply-chain value, strategic criticality, and strategic score proxies.

Analyst overrides can be added in:

```text
config/relative_score_overrides.csv
```

The override file uses one row per ticker and criterion:

```text
ticker,criterion,score,as_of_date,source,notes
```

Overrides replace the automatic score only for that criterion and are labelled as override-derived in the popup. The relative popup is a comparison aid and does not replace `composite_score`, `technical_asset_score`, `commercial_financial_score`, or `strategic_supply_chain_score`.

## Explainability Output

Each scored company exposes:

- `composite_score`
- `technical_asset_score`
- `commercial_financial_score`
- `strategic_supply_chain_score`
- `benchmark_score`
- `scoring_confidence`
- `data_completeness_score`
- `confidence_level`
- `suggested_peer_group`
- `score_status`
- `rating_label`
- `score_breakdown`
- `benchmark_breakdown`
- `missing_data_fields`
- `applied_stage_gates`
- `reason_codes`
- `explanation_bullets`
- `top_positive_drivers`
- `top_negative_drivers`

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

- The score is a screening and prioritisation framework, not a definitive valuation or investment recommendation.
- Market cap, 52-week range, exchange, and segment affect visibility but not the numeric score.
- The benchmark layer depends on supplied project and sector-benchmark fields. If those inputs are sparse, the score remains low-confidence and the missing fields are shown.
- Management quality, detailed capex/opex engineering, tax, sovereign-risk modelling, and legal due diligence are not yet modelled directly.
- LSE tearsheets are not available for every company.
- Some fallback metrics use different debt definitions, so the table labels the debt basis.
- Discovery pipeline fields are manually curated and should be reviewed before formal use.
- Rare Earth Exchanges data should be imported manually or through a compliant workflow; credentials must not be stored in the repo.

## Recommended Next Methodology Work

Useful future improvements:

1. Add curated sector-benchmark files for REE project metrics.
2. Add project-level fixtures for verified reserve/resource, metallurgy, and study economics.
3. Add management, permitting, capex/opex, and catalyst-timing modules.
4. Add explicit peer-group benchmarks for miners, processors, separators, recyclers, and magnet businesses.
