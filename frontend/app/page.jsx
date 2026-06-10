"use client";
// TradeCrew — trading-platform dashboard (REQ-024)
// Nav: Dashboard · Signals · Positions · Accounts. Asset-class chips
// segment everything; every signal row carries its lifecycle + actions.
import { useCallback, useEffect, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8031";

const fmt = (n, sign) =>
  n == null ? "—" :
  (sign && n > 0 ? "+" : "") +
  Number(n).toLocaleString("en-US", { maximumFractionDigits: 2 });
const pnlColor = (n) => (n > 0 ? "#3fb950" : n < 0 ? "#f85149" : "#8b949e");

const CLASSES = [
  { key: "all", label: "All" },
  { key: "equity", label: "Stocks" },
  { key: "options", label: "Options" },
  { key: "crypto", label: "Crypto" },
  { key: "fx", label: "FX" },
  { key: "bond", label: "Bonds" },
  { key: "commodity", label: "Commodities" },
];
const CLASS_COLOR = { equity: "#58a6ff", crypto: "#e3b341", fx: "#bc8cff",
                      bond: "#3fb950", commodity: "#f0883e", options: "#8b949e" };
const AGENT_COLOR = { RESEARCH: "#58a6ff", TRADER: "#e3b341",
                      EXECUTOR: "#3fb950", MONITOR: "#bc8cff", SESSION: "#8b949e" };

const card = { background: "#161b22", border: "1px solid #30363d",
               borderRadius: 12, padding: "12px 14px" };
const btn = (bg, small) => ({
  background: bg, color: "#fff", border: "none", borderRadius: 8,
  padding: small ? "4px 10px" : "9px 16px", fontWeight: 700,
  cursor: "pointer", fontFamily: "inherit", fontSize: small ? 11 : 13 });
const chip = (on, c) => ({
  padding: "5px 12px", borderRadius: 999, fontSize: 11.5, fontWeight: 700,
  cursor: "pointer", whiteSpace: "nowrap", border: `1.5px solid ${on ? c : "#30363d"}`,
  background: on ? `${c}26` : "transparent", color: on ? c : "#8b949e" });
const tag = (c) => ({ fontSize: 9, fontWeight: 800, color: c,
  border: `1px solid ${c}66`, background: `${c}1a`, borderRadius: 5,
  padding: "1.5px 6px", letterSpacing: 0.5, textTransform: "uppercase" });

export default function App() {
  const [tab, setTab] = useState("dashboard");
  const [cls, setCls] = useState("all");
  const [sessions, setSessions] = useState([]);
  const [sid, setSid] = useState(null);
  const [snap, setSnap] = useState(null);
  const [summary, setSummary] = useState(null);
  const [log, setLog] = useState([]);
  const [pnl, setPnl] = useState([]);
  const [notes, setNotes] = useState([]);
  const [setups, setSetups] = useState([]);
  const [trades, setTrades] = useState([]);
  const [expanded, setExpanded] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const pnlAt = useRef(0);

  const j = useCallback(async (path, opts) => {
    const r = await fetch(`${API}/v1${path}`, opts);
    if (!r.ok) throw new Error((await r.json()).message || r.status);
    return r.json();
  }, []);

  const refresh = useCallback(async () => {
    try {
      const ss = await j("/sessions");
      setSessions(ss);
      const cur = sid || (ss.length ? ss[ss.length - 1].sessionId : null);
      if (!sid && cur) setSid(cur);
      if (!cur) return setErr(null);
      setSnap(await j(`/sessions/${cur}/snapshot`));
      setSummary(await j(`/sessions/${cur}/summary`));
      setLog(await j(`/sessions/${cur}/log?limit=14`));
      setNotes(await j(`/sessions/${cur}/research-notes`));
      setSetups(await j(`/sessions/${cur}/setups`));
      setTrades(await j(`/sessions/${cur}/trades`));
      if (Date.now() - pnlAt.current > 15000) {
        pnlAt.current = Date.now();
        j(`/sessions/${cur}/pnl`).then(setPnl).catch(() => {});
      }
      setErr(null);
    } catch (e) {
      setErr(`API unreachable at ${API} — is the orchestrator running? (${e.message})`);
    }
  }, [j, sid]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 2500);
    return () => clearInterval(t);
  }, [refresh]);

  const start = async () => {
    setBusy(true);
    try {
      const s = await j("/sessions", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tickSeconds: 4 }) });
      setSid(s.sessionId);
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const halt = async () => { try { await j(`/sessions/${sid}/halt`,
    { method: "POST" }); } catch {} refresh(); };
  const closePos = async (pid) => { try {
    await j(`/sessions/${sid}/positions/${pid}/close`, { method: "POST" });
  } catch (e) { setErr(e.message); } refresh(); };

  const session = sessions.find((s) => s.sessionId === sid);
  const running = session?.state === "running";
  const open = snap?.openPositions || [];
  const byClass = (arr, key = "asset_class") =>
    cls === "all" ? arr : arr.filter((x) => x[key] === cls);

  // latest scan only, deduped by ticker, ranked by conviction
  const latestNotes = Object.values(
    notes.reduce((m, n) => { m[n.ticker] = n; return m; }, {})
  ).sort((a, b) => b.conviction - a.conviction);

  return (
    <main style={{ maxWidth: 680, margin: "0 auto", padding: "0 12px 70px" }}>

      {/* ===== top nav ===== */}
      <nav style={{ position: "sticky", top: 0, zIndex: 10,
                    background: "rgba(13,17,23,.92)", backdropFilter: "blur(8px)",
                    borderBottom: "1px solid #21262d", margin: "0 -12px",
                    padding: "10px 14px" }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 26, height: 26, borderRadius: 7,
              background: "linear-gradient(135deg,#1f6feb,#e3b341)",
              display: "grid", placeItems: "center", fontSize: 13 }}>📈</div>
            <div>
              <span style={{ fontSize: 16, fontWeight: 800 }}>
                Trade<span style={{ color: "#e3b341" }}>Crew</span></span>
              <span style={{ fontSize: 9.5, color: "#8b949e", marginLeft: 6 }}>
                PAPER · watsonx.data</span>
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ ...tag(running ? "#3fb950" : "#8b949e") }}>
              {session?.state || "no session"}</span>
            {running
              ? <button style={btn("#da3633", true)} onClick={halt}>HALT</button>
              : <button style={btn("#238636", true)} disabled={busy}
                        onClick={start}>{busy ? "…" : "▶ START"}</button>}
          </div>
        </div>
        <div style={{ display: "flex", gap: 16, marginTop: 10 }}>
          {[["dashboard", "Dashboard"], ["signals", "Signals"],
            ["positions", "Positions"], ["accounts", "Accounts"]].map(([k, l]) => (
            <div key={k} onClick={() => setTab(k)}
                 style={{ fontSize: 12.5, fontWeight: 700, cursor: "pointer",
                          paddingBottom: 7,
                          color: tab === k ? "#e6edf3" : "#8b949e",
                          borderBottom: tab === k
                            ? "2px solid #e3b341" : "2px solid transparent" }}>
              {l}{k === "signals" && latestNotes.length
                ? <span style={{ color: "#e3b341" }}> {latestNotes.length}</span> : ""}
            </div>
          ))}
        </div>
      </nav>

      {err && <div style={{ ...card, borderColor: "#f85149", color: "#f85149",
                            margin: "12px 0", fontSize: 12 }}>{err}</div>}

      {/* ===== asset-class segmentation ===== */}
      {tab !== "accounts" && (
        <div style={{ display: "flex", gap: 6, overflowX: "auto",
                      padding: "12px 0 2px" }}>
          {CLASSES.map((c) => (
            <span key={c.key} onClick={() => setCls(c.key)}
                  style={chip(cls === c.key, CLASS_COLOR[c.key] || "#e6edf3")}>
              {c.label}</span>
          ))}
        </div>
      )}
      {cls === "options" && tab !== "accounts" && (
        <div style={{ ...card, margin: "10px 0", fontSize: 12, color: "#8b949e" }}>
          🛠 <b style={{ color: "#e6edf3" }}>Options — roadmap.</b> No options
          data in the workshop cluster; the risk engine (REQ-004/005/006) is
          written to extend to defined-risk options strategies. See
          Requirements.md out-of-scope #3.
        </div>
      )}

      {/* ============ DASHBOARD ============ */}
      {tab === "dashboard" && <>
        <Pipeline log={log} running={running} />
        <section style={{ display: "grid", gap: 8, margin: "10px 0",
                          gridTemplateColumns: "repeat(3, 1fr)" }}>
          {[["sim date", snap?.simulatedDate ?? "—", "#e6edf3"],
            ["realized", fmt(snap?.realizedPnlSession, true),
             pnlColor(snap?.realizedPnlSession)],
            ["unrealized", fmt(snap?.unrealizedPnlTotal, true),
             pnlColor(snap?.unrealizedPnlTotal)],
            ["buying power", fmt(snap?.remainingBuyingPower), "#e6edf3"],
            ["win rate", summary?.trades_closed
              ? `${Math.round(summary.win_rate * 100)}%` : "—", "#e6edf3"],
            ["trades", summary?.trades_closed ?? "—", "#e6edf3"],
          ].map(([k, v, c]) => (
            <div key={k} style={{ ...card, padding: "9px 11px" }}>
              <div style={{ fontSize: 9, color: "#8b949e",
                            textTransform: "uppercase" }}>{k}</div>
              <div style={{ fontSize: 15, fontWeight: 800, color: c }}>{v}</div>
            </div>
          ))}
        </section>
        <OpenPositions open={byClass(open)} closePos={closePos} compact />
        {pnl.length > 0 && (
          <section style={{ ...card, margin: "10px 0" }}>
            <Hdr>HOT + COLD P/L — one federated query (Cassandra ⋈ Iceberg)</Hdr>
            {pnl.map((r, i) => (
              <Row key={i}
                   left={<><span style={tag(r.state === "OPEN" ? "#3fb950" : "#8b949e")}>
                     {r.state}</span> <b style={{ marginLeft: 6 }}>{r.ticker}</b>
                     <span style={{ color: "#8b949e" }}> ×{r.quantity}</span></>}
                   right={<span style={{ color: pnlColor(r.pnl), fontWeight: 700 }}>
                     {fmt(r.pnl, true)}</span>} />
            ))}
          </section>
        )}
        <section style={{ ...card, margin: "10px 0" }}>
          <Hdr>AGENT DECISION LOG</Hdr>
          {log.map((l, i) => (
            <div key={i} style={{ fontSize: 11.5, padding: "4px 0",
                  borderTop: i ? "1px solid #21262d" : "none", lineHeight: 1.5 }}>
              <span style={{ color: AGENT_COLOR[l.agent] || "#8b949e",
                             fontWeight: 700 }}>{l.agent}</span>
              <span style={{ color: "#484f58" }}> {l.at} d={l.simDate} </span>
              <span style={{ color: "#c9d1d9" }}>{l.message}</span>
            </div>
          ))}
          {!log.length && <Empty>no session yet — hit ▶ START</Empty>}
        </section>
      </>}

      {/* ============ SIGNALS ============ */}
      {tab === "signals" && (
        <section style={{ ...card, margin: "10px 0" }}>
          <Hdr>RESEARCH SIGNALS — every signal carries its action</Hdr>
          {byClass(latestNotes).map((n) => {
            const setup = setups.filter((s) => s.note_id === n.note_id)
                                .sort((a, b) => (a.setup_id < b.setup_id ? 1 : -1))[0];
            const pos = open.find((p) => p.ticker === n.ticker);
            const isOpen = expanded === n.note_id;
            return (
              <div key={n.note_id}
                   style={{ borderTop: "1px solid #21262d", padding: "9px 0" }}>
                <div style={{ display: "flex", justifyContent: "space-between",
                              alignItems: "center", gap: 8 }}>
                  <div style={{ minWidth: 0 }}>
                    <b>{n.ticker}</b>{" "}
                    <span style={tag(CLASS_COLOR[n.asset_class] || "#8b949e")}>
                      {n.asset_class}</span>{" "}
                    <span style={{ fontSize: 10.5, color:
                      n.direction === "bullish" ? "#3fb950" :
                      n.direction === "bearish" ? "#f85149" : "#8b949e" }}>
                      {n.direction === "bullish" ? "▲" :
                       n.direction === "bearish" ? "▼" : "▶"} {n.direction}</span>
                    <div style={{ display: "flex", alignItems: "center",
                                  gap: 6, marginTop: 4 }}>
                      <div style={{ width: 90, height: 5, background: "#21262d",
                                    borderRadius: 3 }}>
                        <div style={{ width: `${n.conviction * 100}%`, height: 5,
                          borderRadius: 3,
                          background: n.conviction >= 0.7 ? "#3fb950"
                            : n.conviction >= 0.5 ? "#e3b341" : "#f85149" }} />
                      </div>
                      <span style={{ fontSize: 10, color: "#8b949e" }}>
                        conviction {n.conviction.toFixed(2)}</span>
                    </div>
                  </div>
                  {/* the ACTION cell — one per signal */}
                  <div style={{ textAlign: "right", flexShrink: 0 }}>
                    {pos ? <>
                      <div style={{ color: pnlColor(pos.unrealized_pnl),
                                    fontWeight: 800, fontSize: 13 }}>
                        {fmt(pos.unrealized_pnl, true)}</div>
                      <button style={btn("#da3633", true)}
                              onClick={() => closePos(pos.position_id)}>
                        CLOSE NOW</button>
                    </> : setup?.status === "executed" ? (
                      <span style={tag("#3fb950")}>filled</span>
                    ) : setup?.status === "approved" ? (
                      <span style={tag("#e3b341")}>queued — fills next bar</span>
                    ) : setup?.status === "rejected" ? (
                      <span style={tag("#f85149")}>
                        blocked: {setup.reject_reason}</span>
                    ) : n.shortlisted ? (
                      <span style={tag("#58a6ff")}>shortlisted</span>
                    ) : (
                      <span style={tag("#8b949e")}>watching</span>
                    )}
                    <div onClick={() => setExpanded(isOpen ? null : n.note_id)}
                         style={{ fontSize: 10, color: "#58a6ff",
                                  cursor: "pointer", marginTop: 4 }}>
                      {isOpen ? "hide ▴" : "why? ▾"}</div>
                  </div>
                </div>
                {isOpen && (
                  <div style={{ fontSize: 11.5, color: "#c9d1d9", marginTop: 7,
                                background: "#0d1117", borderRadius: 8,
                                padding: "8px 10px", lineHeight: 1.6 }}>
                    {n.rationale}
                    {n.news_context && <div style={{ marginTop: 6,
                      color: "#8b949e" }}>🌐 <i>{n.news_context}</i></div>}
                    {setup && <div style={{ marginTop: 6, color: "#8b949e" }}>
                      plan: entry {fmt(setup.entry_price)} · stop{" "}
                      {fmt(setup.stop_loss)} · target {fmt(setup.take_profit)} ·
                      risk {fmt(setup.risk_amount)}</div>}
                  </div>
                )}
              </div>
            );
          })}
          {!byClass(latestNotes).length &&
            <Empty>no signals in this class yet</Empty>}
        </section>
      )}

      {/* ============ POSITIONS ============ */}
      {tab === "positions" && <>
        <OpenPositions open={byClass(open)} closePos={closePos} />
        <section style={{ ...card, margin: "10px 0" }}>
          <Hdr>CLOSED TRADES (realized)</Hdr>
          {byClass(trades).slice().reverse().map((t, i) => (
            <Row key={i}
              left={<><b>{t.ticker}</b>
                <span style={{ color: "#8b949e" }}> ×{t.quantity} · </span>
                <span style={tag(t.exit_reason === "trader" ? "#e3b341" : "#8b949e")}>
                  {t.exit_reason}</span>
                <div style={{ fontSize: 10.5, color: "#8b949e", marginTop: 2 }}>
                  {fmt(t.entry_price)} → {fmt(t.exit_price)} · {t.holding_days}d
                </div></>}
              right={<span style={{ color: pnlColor(t.realized_pnl),
                fontWeight: 800 }}>{fmt(t.realized_pnl, true)}</span>} />
          ))}
          {!byClass(trades).length && <Empty>nothing realized yet</Empty>}
        </section>
      </>}

      {/* ============ ACCOUNTS ============ */}
      {tab === "accounts" && <>
        <section style={{ ...card, margin: "12px 0",
                          borderColor: "#3fb950" }}>
          <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "center" }}>
            <div>
              <span style={tag("#3fb950")}>connected</span>
              <div style={{ fontWeight: 800, marginTop: 5 }}>
                watsonx.data Paper Account</div>
              <div style={{ fontSize: 11, color: "#8b949e" }}>
                investment acct {session?.accountId?.slice(0, 8) ?? "—"}… ·
                workshop user-31</div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: 9, color: "#8b949e" }}>BUYING POWER</div>
              <div style={{ fontSize: 17, fontWeight: 800 }}>
                {fmt(session?.remainingBuyingPower)}</div>
              <div style={{ fontSize: 10, color: "#8b949e" }}>
                of {fmt(session?.startingBuyingPower)}</div>
            </div>
          </div>
        </section>

        <Hdr style={{ margin: "14px 2px 8px" }}>ADD A BROKERAGE — the upgrade
          ladder (GUIDE.md §5)</Hdr>
        {[{ name: "Alpaca Paper Trading", icon: "🦙", cls: "stocks + crypto",
            blurb: "Real order lifecycle, fake money. Bracket orders map 1:1 to our setups (entry + stop + target). The supported next rung.",
            keys: "ALPACA_KEY_ID · ALPACA_SECRET" },
          { name: "Coinbase Advanced", icon: "🪙", cls: "crypto",
            blurb: "Crypto-only alternative with sandbox environment. Already powering our market data via the public candles API.",
            keys: "COINBASE_KEY · COINBASE_SECRET" },
          { name: "Interactive Brokers", icon: "🏛", cls: "stocks + options + fx",
            blurb: "Full multi-asset reach incl. options — pairs with the options roadmap. Heavier integration (TWS/Gateway).",
            keys: "IB Gateway session" },
        ].map((b) => (
          <section key={b.name} style={{ ...card, marginBottom: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "center", gap: 10 }}>
              <div>
                <span style={{ fontSize: 15 }}>{b.icon}</span>{" "}
                <b>{b.name}</b>{" "}
                <span style={tag("#58a6ff")}>{b.cls}</span>
                <div style={{ fontSize: 11, color: "#8b949e", marginTop: 4,
                              lineHeight: 1.5 }}>{b.blurb}</div>
                <div style={{ fontSize: 10, color: "#484f58", marginTop: 3 }}>
                  needs: {b.keys} in .env</div>
              </div>
              <a href="https://github.com/nycsav/IBM-WatsonX-AI-Agent-Workshop/blob/main/GUIDE.md"
                 target="_blank" rel="noreferrer"
                 style={{ ...btn("#21262d", true), textDecoration: "none",
                          border: "1px solid #30363d", flexShrink: 0 }}>
                SETUP GUIDE →</a>
            </div>
          </section>
        ))}
        <div style={{ ...card, fontSize: 11, color: "#8b949e", lineHeight: 1.6 }}>
          ⚠️ <b style={{ color: "#e6edf3" }}>Paper first, always.</b> The
          executor/monitor were built behind adapter interfaces so a brokerage
          swap never touches agent logic. Real money is rung 4 of the ladder
          and requires the kill-switch, reconciliation, idempotent orders, and
          daily-loss circuit breaker described in GUIDE.md §5 — plus a paper
          track record you've actually reviewed.
        </div>
      </>}

      <footer style={{ fontSize: 10, color: "#484f58", margin: "16px 0",
                       textAlign: "center" }}>
        paper trading only · session {sid ? sid.slice(0, 8) + "…" : "—"} ·
        API {API}
      </footer>
    </main>
  );
}

/* ---------- shared bits ---------- */
function Hdr({ children, style }) {
  return <div style={{ fontSize: 11, color: "#8b949e", letterSpacing: 0.5,
                       marginBottom: 8, fontWeight: 700, ...style }}>
    {children}</div>;
}
function Empty({ children }) {
  return <div style={{ color: "#484f58", fontSize: 13 }}>{children}</div>;
}
function Row({ left, right }) {
  return <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", padding: "6px 0",
                       borderTop: "1px solid #21262d", fontSize: 12.5 }}>
    <div style={{ minWidth: 0 }}>{left}</div>
    <div style={{ flexShrink: 0, marginLeft: 8 }}>{right}</div>
  </div>;
}
function OpenPositions({ open, closePos, compact }) {
  return (
    <section style={{ ...card, margin: "10px 0" }}>
      <Hdr>OPEN POSITIONS ({open.length})</Hdr>
      {open.map((p) => (
        <Row key={p.position_id}
          left={<><b>{p.ticker}</b>
            <span style={{ color: "#8b949e" }}> ×{p.quantity}</span>
            <div style={{ fontSize: 10.5, color: "#8b949e", marginTop: 2 }}>
              in {fmt(p.entry_price)} · now {fmt(p.current_price)} · stop{" "}
              {fmt(p.stop_loss)}{p.trail_armed ? " 🔒(trail)" : ""}</div></>}
          right={<div style={{ textAlign: "right" }}>
            <div style={{ color: pnlColor(p.unrealized_pnl), fontWeight: 800 }}>
              {fmt(p.unrealized_pnl, true)}</div>
            <button onClick={() => closePos(p.position_id)}
                    style={{ ...btn("#21262d", true),
                             border: "1px solid #da3633", color: "#f85149" }}>
              close</button>
          </div>} />
      ))}
      {!open.length && <Empty>book is flat</Empty>}
    </section>
  );
}
function Pipeline({ log, running }) {
  return (
    <section style={{ ...card, marginTop: 10, padding: "10px 8px" }}>
      <div style={{ display: "flex", alignItems: "center",
                    justifyContent: "space-between", gap: 2 }}>
        {[["⏱", "CLOCK", "#8b949e"], ["🔍", "RESEARCH", "#58a6ff"],
          ["⚖️", "TRADER", "#e3b341"], ["⚡", "EXECUTOR", "#3fb950"],
          ["📡", "MONITOR", "#bc8cff"]].map(([icon, name, c], i) => {
          const active = log[0]?.agent === name || (name === "CLOCK" && running);
          return (
            <div key={name} style={{ display: "flex", alignItems: "center",
                                     flex: i ? "1 1 0" : "0 0 auto" }}>
              {i > 0 && <div style={{ flex: 1, height: 2, margin: "0 3px",
                background: "linear-gradient(90deg,#30363d,#484f58)" }} />}
              <div style={{ textAlign: "center", padding: "5px 7px",
                borderRadius: 8, border: `1.5px solid ${active ? c : "#30363d"}`,
                background: active ? `${c}22` : "transparent",
                boxShadow: active ? `0 0 10px ${c}55` : "none",
                transition: "all .3s" }}>
                <div style={{ fontSize: 14, lineHeight: 1 }}>{icon}</div>
                <div style={{ fontSize: 8.5, fontWeight: 700, color: c,
                              letterSpacing: 0.5 }}>{name}</div>
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ fontSize: 9.5, color: "#484f58", textAlign: "center",
                    marginTop: 6 }}>
        research → setups → fills → monitored exits · risk guardrails at every
        gate · Cassandra hot ⋈ Iceberg cold via Presto
      </div>
    </section>
  );
}
