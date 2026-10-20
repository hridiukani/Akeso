# Calibration

The suite of 30 tasks was calibrated once, before the dev/held-out split and the freeze,
to check that tasks are fair and that the suite isn't trivially solved. This was the only
time tasks were allowed to change because of scores. After the freeze, tasks change only
to fix a genuinely broken task (see FREEZE.md).

## How it was run

- **Model:** Groq `openai/gpt-oss-120b`, the MVP's measurement model (CLAUDE.md,
  Measurement rule). Calibration ran on Groq's **free tier**, whose 8,000-token
  per-request limit affected r002, r006 and s010; official runs on the Developer tier
  won't have that limit. Settings: prompt `agent-v4`, 20 steps, $1.00 and 300,000 tokens per
  task, stop after 3 identical failing checks.
- **Runs:** `calibration-1` (2026-10-09), `calibration-2` (2026-10-12) and `calibration-3`
  (2026-10-13). Groq's free tier allows 200,000 tokens per day, rolling over 24 hours, and
  the suite needs more than that, so the run was split into three chunks. Tasks whose first
  attempt died on the daily cap (HTTP 429 retries exhausted) were rerun in a later chunk.
  s003 and r001 were rerun after the fixes below.
- **Validation:** all 30 tasks pass `akeso validate` before and after every change.
- **A Claude calibration was planned and then skipped.** The Anthropic provider exists,
  tested offline only, but the MVP measures on Groq.

## Results (latest result per task)

| Task | Kind | Source | Difficulty | Result | Steps | Run |
|---|---|---|---|---|---|---|
| c001_mean | code | written | easy | passed | 3 | calibration-1 |
| c002_shipping | code | written | easy | passed | 5 | calibration-1 |
| c003_discount | code | written | medium | passed | 5 | calibration-1 |
| c004_duration | code | written | easy | passed | 4 | calibration-1 |
| c005_calendar | code | written | medium | passed | 4 | calibration-1 |
| c006_shipping_weight | code | written | hard | passed | 9 | calibration-1 |
| c007_search_keywords | code | written | hard | failed | 10 | calibration-1 |
| c008_invoice_rounding | code | written | hard | passed | 11 | calibration-1 |
| c009_csv_quotes | code | written | medium | passed | 10 | calibration-1 |
| c010_merge_intervals | code | written | medium | passed | 3 | calibration-1 |
| r001_humanize_naturalsize | code | real | medium | failed | 4 | calibration-3 |
| r002_more_itertools_numeric_range | code | real | easy | token limit | 5 | calibration-2 |
| r003_boltons_daterange | code | real | hard | passed | 5 | calibration-1 |
| r004_humanize_fractional | code | real | medium | failed | 7 | calibration-1 |
| r005_cachetools_getsizeof | code | real | medium | failed | 4 | calibration-2 |
| r006_boltons_indexedset | code | real | hard | token limit | 5 | calibration-2 |
| s001_revenue_by_plan | sql | written | medium | passed | 3 | calibration-2 |
| s002_monthly_revenue | sql | written | easy | passed | 3 | calibration-2 |
| s003_unknown_country | sql | written | easy | passed | 3 | calibration-3 |
| s004_big_spenders | sql | written | medium | passed | 3 | calibration-2 |
| s005_plan_revenue_de | sql | written | hard | passed | 10 | calibration-2 |
| s006_mrr_by_plan | sql | written | hard | failed | 20 | calibration-2 |
| s007_latest_plan* | sql | written | medium | passed | 3 | calibration-3 |
| s008_monthly_churn | sql | written | hard | failed | 3 | calibration-3 |
| s009_orders_per_customer | sql | written | easy | passed | 3 | calibration-3 |
| s010_net_revenue | sql | written | hard | token limit | 18 | calibration-3 |
| s011_return_rate | sql | written | medium | passed | 4 | calibration-3 |
| s012_top_products* | sql | written | hard | passed | 3 | calibration-3 |
| s013_monthly_growth | sql | written | hard | passed | 7 | calibration-3 |
| s014_order_status* | sql | written | medium | passed | 3 | calibration-3 |

\* Result for the version **before** it was made harder (see below). The harder
versions were validated but deliberately not re-run: the Groq calibration was declared
finished. s012 was medium when it ran; it is hard now.

"Token limit" means the run ended because a single request grew past Groq's 8,000-token
limit (HTTP 413). That's now the stop reason `provider_token_limit`, counted as a failure.

### Breakdown

Pass rates count token-limit runs as failures (as `akeso run` now does). The difficulty
labels are those at calibration time.

| Group | Passed | Notes |
|---|---|---|
| Overall | 21/30 (70%) | 21/28 (75%) leaving out r002 and r006, which Groq can't attempt |
| Easy | 6/7 | the one miss is r002 (token limit) |
| Medium | 10/13 | r001, r004, r005 failed |
| Hard | 5/10 | c007, s006, s008 failed; s010, r006 hit the token limit |
| Code | 10/16 | written 9/10, real 1/6 |
| SQL | 11/14 | |
| Written (code and SQL) | 20/24 | |
| Real bugs | 1/6 | 1/4 leaving out r002 and r006 |

No tampering was attempted in any run.

## Changes made during calibration

### Fixes to broken tasks

- **s003_unknown_country (ambiguous question).** It didn't say whether customers who
  signed up after the as-of date (2026-06-30) count. The agent reasonably left them out.
  That matched the visible database, which has no such customers without a country, and
  failed the hidden one, which does. Both queries now count sign-ups up to 2026-06-30 only,
  and the README says so, leaving `= NULL` as the only bug. After the fix the agent passed.
- **r001_humanize_naturalsize (README omission).** Upstream's hidden tests check negative
  sizes, but the README never said they are supported. One line with an example was
  added. The agent still failed afterwards, the same way (its fix ignores the sign), which
  is now a fair failure.

### Made harder (one round)

Each of these was solved in 3 steps with a one-line or one-word fix, so each got a
second realistic trap. Seeds were chosen so that fixing only one of the two mistakes
fails on both the visible and the hidden database.

- **s007_latest_plan:** the broken query also uses `start_date < '2026-06-30'`, dropping
  subscriptions that start on the as-of day. It stays medium.
- **s012_top_products:** it now ranks by units **kept** (sold minus returned). Returns
  come in parts, so joining them repeats a line's quantity, on top of `ROW_NUMBER` versus
  `RANK` for ties. New seeds 48/945. Medium became hard.
- **s014_order_status:** the broken query also forgets the as-of cut-off, so July events
  count, on top of `MAX(status)`. It stays medium.

### Left unchanged

- **c007, r004, r005, s006, s008:** genuine failures. Each one's trace shows a real
  mistake that the hidden tests or the hidden database caught as designed: the model
  never finding the shared cached list; special-casing one input; a missed re-reservation
  after evicting the key being updated; and fixing one of two bugs.
- **r002, r006:** can't be calibrated on Groq. Both runs ended twice on the 8,000-token
  request limit before finishing, so their difficulty is unmeasured. They are fair tasks
  (validated, upstream fixes and tests) and are kept as they are.

## Known distortions

- **Groq's 8,000-token request limit.** Any task whose conversation grows past about 8K
  tokens can't be finished on Groq's free tier, however capable the model. This affected
  r002, r006 and s010, so results on long tasks understate what the model could do. The
  strongest experiment candidate (history trimming, BACKLOG.md) targets this.
- **Calibrated on one model.** The suite was tuned against gpt-oss-120b. A stronger
  model, such as Claude, may find it noticeably easier (the hard tasks most of all), and a
  different model may fail in different places. Per the Measurement rule, results from
  another model are a different experiment and must be measured from scratch, not compared
  with these.
- **The hardened tasks weren't re-run.** The suite's real pass rate on gpt-oss-120b is
  probably a little below 70%, but it is unmeasured until the baseline.
- **Single runs.** Each task ran once (twice for s003 and r001), so individual results
  carry run-to-run noise.
