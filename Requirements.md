# Requirements — Multi-Agent Trading System ("TradeCrew")

**Workshop**: watsonx.data shared-cloud workshop · June 10, 2026
**Attendee**: user-31 · **Domain**: Financial
**Document status**: Draft v3 — requirements only; no implementation details.

---

## 1. Purpose

A multi-agent system that acts as a busy retail trader's automated
investment team: an investment researcher/analyst, an expert trade-setup
specialist, a trade executor, and a live-trade monitor.

The trader does not have time to actively manage a portfolio in a volatile
market. The system therefore automates the research and trading work,
continuously tracks profit and loss, and — the part traders find hardest —
enforces risk management by actually *taking the actions*: placing trades
within strict risk limits and exiting them on a plan that adapts to the
market, without waiting for the human.

The trader's growth goal is diversification beyond single-asset investing,
across the asset classes available in the workshop's market dataset
(equities, bonds, FX, commodities, crypto).

All activity is simulation against the workshop's pre-loaded financial
dataset. No real money, brokerage, or external market connectivity is
involved.

---

## 2. Personas

| ID | Persona | Description | Goals & pain points |
|---|---|---|---|
| P-1 | **Busy Retail Trader** (primary — app user & account owner) | A working professional with a full work day and personal life. Checks in from a mobile device in stolen moments — commutes, lunch, evenings. Comfortable with AI tools (ChatGPT, Claude, Perplexity) and browser-based platforms; expects to delegate to an AI and review its reasoning, not babysit it. | **Goals**: grow and diversify the portfolio (multi-asset, eventually options/crypto/RWA) without giving it work-day attention; have research, trade placement, exits, and P/L tracking fully automated. **Pain points**: no time to watch a volatile market; the hardest part is risk management and actually pulling the trigger — placing a trade and exiting it on plan instead of hesitating or holding losers. |
| P-2 | **Reviewer / Auditor** | Anyone verifying the system's behavior after the fact — the trader themselves doing a weekend review, or a workshop evaluator. | Reconstruct any trade's full story — why it was proposed, when it was entered, how the exit plan evolved, why and when it closed — from recorded data alone. |

> The trader is both the operator and the account owner: it is their
> account, their risk limits, and their session — but the system must run
> without them present.

---

## 3. User flows

### UF-1 — Delegate a trading session (P-1)
1. The trader starts a session (e.g., in the morning before work) and does
   nothing further.
2. The Researcher analyzes the market across all eligible asset classes
   and publishes ranked research notes with plain-language rationale —
   readable the way the trader is used to reading an LLM's reasoning.
3. The Trader converts the strongest notes into trade setups with entry,
   size, and a complete exit plan, enforcing the trader's risk limits;
   setups that fail guardrails are rejected with a stated reason.
4. The Executor places approved trades automatically — no confirmation
   prompt blocks on the absent trader.
5. The Monitor tracks every open position as prices move, tightens exits
   when trades go well, and closes positions when the plan says so —
   while the trader is in a meeting.
6. The session ends (trader stops it, or the price stream is exhausted);
   the trader receives a session summary they can absorb in under a
   minute.

### UF-2 — Quick check-in (P-1)
1. Mid-day, the trader has two minutes between meetings.
2. They request a status snapshot and immediately see: open positions
   with live unrealized P/L, each position's current exit plan, today's
   realized P/L, and the last few agent decisions.
3. Reading it requires no scrolling through raw logs and no queries; they
   put the phone away and get back to work.

### UF-3 — Intervene (P-1)
1. The trader decides to take profit early on one position, or to halt
   everything (e.g., unexpected market news).
2. With a single action, the system closes the requested position(s) at
   the current market price, records the exit as trader-initiated, and
   (on halt) stops opening new positions.
3. The trader does not need to compute anything — the system reports what
   the action realized.

### UF-4 — Review & audit (P-1, P-2)
1. In the evening or on the weekend, the reviewer examines the recorded
   history: per-session and cumulative P/L, win rate, and drawdown.
2. For any closed trade, they can trace: the research note that motivated
   it → the setup and its risk parameters → the execution record → every
   exit-plan adjustment → the exit record with reason and realized P/L.
3. The trader uses this to build trust in the automation — or to tighten
   its risk limits.

---

## 4. Functional requirements

Each requirement has acceptance criteria (AC). A requirement is satisfied
only when all its ACs pass.

### Research & analysis

**REQ-001 — Market scan.** The Researcher shall analyze recent market
history for every instrument available in the workshop's market dataset,
across all asset classes present (equity, bond, FX, commodity, crypto),
as of the session's current simulated date.
- AC-1: Every available instrument is either analyzed or explicitly
  skipped with a stated reason (e.g., insufficient history).
- AC-2: The analysis uses only data up to the current simulated date;
  no future data ("lookahead") is ever used.
- AC-3: No asset class present in the dataset is silently ignored.

**REQ-002 — Research notes.** For each analyzed instrument the Researcher
shall produce a research note containing a market view (direction,
momentum, and volatility characterization), a conviction score on a
defined scale, and a plain-language rationale.
- AC-1: Every note contains all three elements; the rationale reads like
  an analyst's explanation a non-professional can follow (the trader is
  used to LLM-style reasoning, not broker shorthand).
- AC-2: Conviction scores are comparable across instruments and asset
  classes (same scale, same date basis).

**REQ-003 — Shortlist.** The Researcher shall rank instruments by
conviction and publish a shortlist of candidates for trading, of a
configurable maximum size.
- AC-1: The shortlist never exceeds the configured size.
- AC-2: Every shortlisted instrument has a research note; ranking order is
  reproducible from the notes' conviction scores.

### Trade setups & risk management

**REQ-004 — Complete setups.** For each shortlisted instrument the Trader
shall produce a trade setup specifying: instrument, asset class,
direction, entry price, position size, initial stop-loss, profit target,
and the rule by which the exit plan tightens as the trade becomes
profitable.
- AC-1: No setup is ever published with any of these elements missing.
- AC-2: Every setup's profit target represents at least twice the risk
  taken between entry and initial stop-loss (minimum 2:1 reward-to-risk).

**REQ-005 — Position sizing.** Position size shall be derived from the
trader's available balance such that a trade stopping out at its initial
stop-loss loses no more than a configured percentage of the account
(default 1%).
- AC-1: For every executed trade, (entry − stop) × size ≤ the configured
  per-trade risk budget at the time of setup.
- AC-2: A setup whose minimum viable size would breach the budget is
  rejected, not shrunk below viability silently.

**REQ-006 — Risk guardrails.** The Trader shall reject setups that violate
account-level guardrails: maximum concurrent open positions (default 5),
maximum aggregate open risk (default 3% of account), and the trader's
risk profile (no trading for high-risk/restricted profiles).
- AC-1: Each rejection is recorded with the specific guardrail that
  triggered it.
- AC-2: At no moment during a session do open positions exceed the
  concurrency or aggregate-risk limits.

**REQ-019 — Diversification.** The system shall diversify across asset
classes: a configurable cap shall limit how much of the aggregate open
risk any single asset class may consume (default: no more than 50%), and
when comparably ranked candidates exist in different asset classes, the
shortlist shall prefer breadth over concentration.
- AC-1: At no moment does one asset class's share of aggregate open risk
  exceed the configured cap (when eligible candidates existed elsewhere).
- AC-2: A session run over a dataset containing multiple asset classes
  with valid candidates opens positions in at least two asset classes.

### Execution

**REQ-007 — Paper execution.** The Executor shall fill approved setups as
simulated orders at a realistic price (no fill at a price the market never
offered; no same-moment hindsight fills).
- AC-1: Every fill price falls within the market's actual traded range for
  the moment of execution.
- AC-2: Every fill produces an execution record (instrument, asset class,
  direction, price, size, time) and an open position visible to the
  trader.

**REQ-008 — Buying-power accounting.** Capital committed to open positions
shall be tracked so it cannot be committed twice.
- AC-1: The sum of committed capital plus remaining buying power always
  equals the starting buying power (until positions close and release it).
- AC-2: A setup requiring more capital than the remaining buying power is
  rejected.

**REQ-020 — Unattended operation.** From session start to session end, the
system shall require no human input: research, trade placement, exit-plan
management, and exits all execute automatically. The trader's hardest
problem — hesitating on entries and exits — is solved by the system never
waiting for them.
- AC-1: A full session (start → research → trades → exits → summary)
  completes with zero operator interactions.
- AC-2: No agent ever blocks on a confirmation prompt; interventions
  (UF-3) are possible but never required.

### Monitoring, exits & P/L tracking

**REQ-009 — Continuous monitoring.** The Monitor shall re-evaluate every
open position against current market prices on a regular cycle for the
whole life of the position.
- AC-1: No open position ever misses a monitoring cycle while the session
  runs.
- AC-2: Each cycle records the position's current price and unrealized
  profit/loss.

**REQ-010 — Exit plan enforcement.** The Monitor shall close a position
when its stop-loss, profit target, or tightened (trailing) exit level is
reached, using a defined priority order when multiple conditions occur in
the same cycle.
- AC-1: Every closed trade's exit reason is one of: stop-loss, profit
  target, trailing exit, trader-initiated, or session end.
- AC-2: In any test scenario where an exit condition is reached, the
  position is closed in that same monitoring cycle — never carried in
  hope of recovery.

**REQ-011 — Adaptive exit plan.** Once a position has gained at least the
amount originally risked, the Monitor shall begin tightening the exit
level in the direction of profit; the exit level shall never be loosened.
- AC-1: For every position, the recorded sequence of exit levels is
  monotonic (never moves against the trade).
- AC-2: A trade that retraces after triggering tightening exits at no
  worse than its tightened level.

**REQ-021 — Automated P/L tracking.** The system shall maintain, without
being asked, a continuously current profit-and-loss picture: unrealized
P/L per open position, realized P/L per closed trade, and running session
totals.
- AC-1: At any moment during a session, the trader can obtain current
  unrealized and realized P/L without triggering any recomputation ritual
  — the figures are already maintained.
- AC-2: Realized P/L totals always reconcile exactly with the closed-trade
  records.

**REQ-012 — Trade archival.** Every closed trade shall be recorded with
entry and exit price/time, realized profit/loss, exit reason, and holding
period, and remain queryable after the session ends.
- AC-1: Closed-trade records are complete for 100% of closed trades.
- AC-2: The audit chain of UF-4 (note → setup → execution → adjustments →
  exit) is reconstructible for any sampled trade.

### Session & observability

**REQ-013 — Simulated live market.** The system shall derive a steady
stream of "current" prices from the workshop's historical market data,
advancing simulated time as the session runs, identically visible to all
agents.
- AC-1: All agents observe the same current simulated date/price at any
  given moment.
- AC-2: The stream's pace is configurable; a complete session (research
  through at least one closed trade) finishes within a few minutes at
  default pace.

**REQ-014 — Decision log.** Every material agent decision (note published,
setup proposed/rejected, order filled, exit adjusted, position closed)
shall be announced as a human-readable, timestamped log line as it
happens.
- AC-1: A trader reading only the log can narrate the session's story
  without querying anything.
- AC-2: Log lines identify the acting agent and the affected instrument.

**REQ-022 — Quick-glance status snapshot.** On demand, the system shall
produce a compact status snapshot: open positions with unrealized P/L and
current exit levels, today's realized P/L, remaining buying power, and the
most recent agent decisions.
- AC-1: The snapshot is consumable by a busy reader in under a minute —
  one screenful, most important figures first.
- AC-2: Requesting a snapshot never disturbs the running session.

**REQ-015 — Session summary.** At session end the trader shall receive a
summary: positions opened and closed, win rate, aggregate realized and
unrealized profit/loss, and worst peak-to-trough drawdown.
- AC-1: Summary figures reconcile exactly with the recorded trade history.
- AC-2: The summary distinguishes realized from unrealized results.

**REQ-016 — Unified hot/cold view.** It shall be possible, in a single
query against the workshop platform, to see live open positions together
with historical market and trade data (the workshop's federated hot+cold
demonstration).
- AC-1: One query returns every open position marked to the current market
  price.
- AC-2: The same query path can combine open (live) and closed
  (historical) trades into one profit/loss view.

**REQ-017 — Repeatable sessions.** Starting a new session shall be safe
and repeatable: prior sessions' records are preserved, and re-running
setup steps causes no errors or data loss.
- AC-1: Two consecutive sessions run without manual cleanup between them.
- AC-2: Records from earlier sessions remain queryable and distinguishable
  by session.

### Workshop boundaries

**REQ-018 — Data stewardship.** The system shall only write within the
attendee's own workshop data slices, shall never modify the shared
read-only reference data or other attendees' data, and shall not alter the
pre-loaded account and customer records.
- AC-1: All writes land in user-31's own slices.
- AC-2: Pre-loaded records are byte-identical before and after a session.

---

## 5. Out of scope (explicit)

The following are **not** part of this system, in any version built during
the workshop:

1. **Real trading** — no brokerage connectivity, no real orders, no real
   funds at risk.
2. **Real-time external market feeds** — prices come exclusively from the
   workshop's historical dataset (see REQ-013); no internet price sources.
3. **Options and other derivatives** — a stated trader goal, but the
   workshop dataset has no options data. Roadmap item; the risk-management
   requirements (REQ-004/005/006) are written to extend to defined-risk
   options strategies later.
4. **Real-world assets (RWA)** — no tokenized-asset data exists in the
   workshop dataset. Roadmap item; the diversification requirement
   (REQ-019) treats asset classes generically so RWA can slot in later.
   *(Crypto, by contrast, IS in scope — the dataset contains crypto
   instruments and REQ-001/019 cover them.)*
5. **Short selling and leverage** — long-only, fully-funded spot positions
   across the available asset classes.
6. **A native mobile app, push notifications, or any graphical UI** — the
   trader persona is mobile-first, but the workshop build's interface is
   the decision log, the quick-glance snapshot, and queryable records
   (browsable in the platform's existing UI). Mobile delivery of the
   snapshot/summary is a roadmap item.
7. **Machine-learned models** — conviction and setups follow stated rules;
   no model training; the workshop's fraud/ML datasets are unused.
8. **User management and authentication** — single trader, workshop
   credentials only.
9. **Fractional shares and partial fills** — whole-unit positions,
   all-or-nothing fills.
10. **Tax, fees, commissions, and slippage modeling** — gross profit/loss
    only.
11. **Data durability beyond the workshop** — the cluster is torn down
    afterward; only files on the attendee's laptop persist.
12. **Cluster administration** — no platform operations of any kind; the
    system is strictly a tenant of its assigned slices.

---

## 6. Open questions

1. Which simulated account trades? (Proposed default: the trader's
   investment account with the largest available balance.)
2. Per-asset-class risk cap (REQ-019) — is 50% of aggregate open risk per
   class the right default, or should crypto get a tighter cap given its
   volatility?
3. Session pace at default settings? (Proposed default: one simulated
   trading day per few seconds of wall clock.)
4. Should the quick-glance snapshot (REQ-022) refresh automatically at
   intervals, or only on request? (Proposed default: on request.)
