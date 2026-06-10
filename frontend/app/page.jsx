"use client";
// TradeCrew dashboard (REQ-024) — consumes the FastAPI surface only.
// Phone-first layout; polls every 2.5s; Start / Halt / Close = UF-1/UF-3.
import { useCallback, useEffect, useRef, useState } from "react";

const API =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8031";

const fmt = (n, sign) =>
  n == null ? "—" :
  (sign && n > 0 ? "+" : "") +
  Number(n).toLocaleString("en-US", { maximumFractionDigits: 2 });

const pnlColor = (n) => (n > 0 ? "#3fb950" : n < 0 ? "#f85149" : "#8b949e");

const card = {
  background: "#161b22", border: "1px solid #30363d", borderRadius: 10,
  padding: "12px 14px",
};
const btn = (bg) => ({
  background: bg, color: "#fff", border: "none", borderRadius: 8,
  padding: "10px 16px", fontWeight: 700, cursor: "pointer",
  fontFamily: "inherit", fontSize: 13,
});

export default function Dashboard() {
  const [sessions, setSessions] = useState([]);
  const [sid, setSid] = useState(null);
  const [snap, setSnap] = useState(null);
  const [summary, setSummary] = useState(null);
  const [log, setLog] = useState([]);
  const [pnl, setPnl] = useState([]);
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
      setLog(await j(`/sessions/${cur}/log?limit=12`));
      if (Date.now() - pnlAt.current > 15000) {       // Presto etiquette
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
    try { const s = await j("/sessions", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tickSeconds: 3 }) });
      setSid(s.sessionId);
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const halt = async () => {
    try { await j(`/sessions/${sid}/halt`, { method: "POST" }); } catch {}
    refresh();
  };
  const closePos = async (pid) => {
    try { await j(`/sessions/${sid}/positions/${pid}/close`, { method: "POST" }); }
    catch (e) { setErr(e.message); }
    refresh();
  };

  const session = sessions.find((s) => s.sessionId === sid);
  const open = snap?.openPositions || [];

  return (
    <main style={{ maxWidth: 640, margin: "0 auto", padding: 14 }}>
      <header style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", margin: "6px 0 14px" }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 800 }}>
            Trade<span style={{ color: "#e3b341" }}>Crew</span>
          </div>
          <div style={{ fontSize: 11, color: "#8b949e" }}>
            multi-agent paper trading · watsonx.data
          </div>
        </div>
        {session?.state === "running"
          ? <button style={btn("#da3633")} onClick={halt}>HALT</button>
          : <button style={btn("#238636")} disabled={busy} onClick={start}>
              {busy ? "…" : "START SESSION"}</button>}
      </header>

      {err && <div style={{ ...card, borderColor: "#f85149",
                            color: "#f85149", marginBottom: 12, fontSize: 12 }}>
        {err}</div>}

      {/* Quick-glance (REQ-022) */}
      <section style={{ display: "grid", gap: 8,
                        gridTemplateColumns: "repeat(2, 1fr)", marginBottom: 12 }}>
        {[["sim date", snap?.simulatedDate ?? "—", "#e6edf3"],
          ["state", session?.state ?? "no session", "#e3b341"],
          ["realized P/L", fmt(snap?.realizedPnlSession, true),
           pnlColor(snap?.realizedPnlSession)],
          ["unrealized P/L", fmt(snap?.unrealizedPnlTotal, true),
           pnlColor(snap?.unrealizedPnlTotal)],
          ["buying power", fmt(snap?.remainingBuyingPower), "#e6edf3"],
          ["win rate", summary?.trades_closed
            ? `${Math.round(summary.win_rate * 100)}% of ${summary.trades_closed}`
            : "—", "#e6edf3"],
        ].map(([k, v, c]) => (
          <div key={k} style={card}>
            <div style={{ fontSize: 10, color: "#8b949e",
                          textTransform: "uppercase" }}>{k}</div>
            <div style={{ fontSize: 17, fontWeight: 700, color: c }}>{v}</div>
          </div>
        ))}
      </section>

      {/* Open positions + UF-3 close */}
      <section style={{ ...card, marginBottom: 12 }}>
        <div style={{ fontSize: 12, color: "#8b949e", marginBottom: 8 }}>
          OPEN POSITIONS ({open.length})</div>
        {open.length === 0 &&
          <div style={{ color: "#484f58", fontSize: 13 }}>book is flat</div>}
        {open.map((p) => (
          <div key={p.position_id}
               style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "center", padding: "7px 0",
                        borderTop: "1px solid #21262d", fontSize: 13 }}>
            <div>
              <b>{p.ticker}</b>
              <span style={{ color: "#8b949e" }}> ×{p.quantity}</span>
              <div style={{ fontSize: 11, color: "#8b949e" }}>
                in {fmt(p.entry_price)} · now {fmt(p.current_price)} · stop{" "}
                {fmt(p.stop_loss)}{p.trail_armed ? " (trail)" : ""}
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ color: pnlColor(p.unrealized_pnl), fontWeight: 700 }}>
                {fmt(p.unrealized_pnl, true)}</div>
              <button onClick={() => closePos(p.position_id)}
                      style={{ ...btn("#21262d"), padding: "3px 10px",
                               fontSize: 11, border: "1px solid #30363d" }}>
                close</button>
            </div>
          </div>
        ))}
      </section>

      {/* Federated hot+cold P/L (REQ-016) */}
      {pnl.length > 0 && (
        <section style={{ ...card, marginBottom: 12 }}>
          <div style={{ fontSize: 12, color: "#8b949e", marginBottom: 8 }}>
            HOT + COLD P/L — one federated query (Cassandra ⋈ Iceberg)</div>
          {pnl.map((r, i) => (
            <div key={i} style={{ display: "flex", fontSize: 12,
                                  justifyContent: "space-between",
                                  padding: "3px 0" }}>
              <span>
                <span style={{ color: r.state === "OPEN" ? "#3fb950" : "#8b949e",
                               fontWeight: 700 }}>{r.state}</span>{" "}
                {r.ticker} ×{r.quantity}
              </span>
              <span style={{ color: pnlColor(r.pnl) }}>{fmt(r.pnl, true)}</span>
            </div>
          ))}
        </section>
      )}

      {/* Decision log (REQ-014) */}
      <section style={card}>
        <div style={{ fontSize: 12, color: "#8b949e", marginBottom: 8 }}>
          AGENT DECISION LOG</div>
        {log.map((l, i) => (
          <div key={i} style={{ fontSize: 11.5, padding: "4px 0",
                                borderTop: i ? "1px solid #21262d" : "none",
                                lineHeight: 1.5 }}>
            <span style={{ color: {
              RESEARCH: "#58a6ff", TRADER: "#e3b341", EXECUTOR: "#3fb950",
              MONITOR: "#bc8cff", SESSION: "#8b949e" }[l.agent] || "#8b949e",
              fontWeight: 700 }}>{l.agent}</span>
            <span style={{ color: "#484f58" }}> {l.at} d={l.simDate} </span>
            <span style={{ color: "#c9d1d9" }}>{l.message}</span>
          </div>
        ))}
        {log.length === 0 &&
          <div style={{ color: "#484f58", fontSize: 13 }}>
            no session yet — hit START</div>}
      </section>

      <footer style={{ fontSize: 10, color: "#484f58", margin: "14px 0",
                       textAlign: "center" }}>
        paper trading only · workshop user-31 · API: {API}
      </footer>
    </main>
  );
}
