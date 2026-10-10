import { useEffect, useState, useCallback } from "react";

const short = (s) => (!s ? "" : s.length > 20 ? `${s.slice(0, 4)}…${s.slice(-4)}` : s);
const sol = (n) => (n == null ? "–" : `${n >= 0 ? "+" : ""}${n.toFixed(3)}`);
const pct = (n) => (n == null ? "–" : `${(n * 100).toFixed(0)}%`);
const tone = (n) => (n > 0 ? "text-emerald-400" : n < 0 ? "text-rose-400" : "text-slate-400");
const adviceTone = (label) =>
  ["Take", "Hold", "Sell"].includes(label) ? "text-emerald-400" : ["Cut", "Pass", "Skip"].includes(label) ? "text-rose-400" : "text-amber-300";

function Suggestion({ advice }) {
  if (!advice) return <span className="text-slate-500">–</span>;
  return (
    <div>
      <div className={`text-xs font-semibold ${adviceTone(advice.label)}`}>{advice.label}</div>
      <div className="text-xs text-slate-500">{advice.text}</div>
    </div>
  );
}

function Card({ label, value, sub, cls = "text-slate-100" }) {
  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 p-4">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${cls}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

function Panel({ title, children, right }) {
  return (
    <section className="rounded-xl bg-slate-900 border border-slate-800">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <h2 className="text-sm font-medium text-slate-300">{title}</h2>
        {right}
      </div>
      <div className="overflow-x-auto">{children}</div>
    </section>
  );
}

function Spark({ data }) {
  if (!data || data.length < 2)
    return <div className="p-6 text-sm text-slate-500">Not enough closed trades yet.</div>;
  const w = 600, h = 120, min = Math.min(0, ...data), max = Math.max(0, ...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / span) * h}`);
  const zero = h - ((0 - min) / span) * h;
  const up = data[data.length - 1] >= 0;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-32 p-2" preserveAspectRatio="none">
      <line x1="0" x2={w} y1={zero} y2={zero} stroke="#334155" strokeDasharray="4" />
      <polyline fill="none" strokeWidth="2" stroke={up ? "#34d399" : "#fb7185"} points={pts.join(" ")} />
    </svg>
  );
}

function Login({ onToken }) {
  const [v, setV] = useState("");
  return (
    <div className="min-h-screen grid place-items-center text-slate-100">
      <div className="w-80 space-y-3">
        <h1 className="text-xl font-semibold">Paper Scanner</h1>
        <input
          type="password"
          value={v}
          onChange={(e) => setV(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onToken(v)}
          placeholder="Dashboard token"
          className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 outline-none focus:border-emerald-500"
        />
        <button onClick={() => onToken(v)} className="w-full rounded-lg bg-emerald-600 hover:bg-emerald-500 py-2 font-medium">
          Enter
        </button>
      </div>
    </div>
  );
}

export default function App() {
  const [token, setToken] = useState(localStorage.getItem("dash_token") || "");
  const [sum, setSum] = useState(null);
  const [trades, setTrades] = useState([]);
  const [wallets, setWallets] = useState([]);
  const [cands, setCands] = useState({ candidates: [], sources: {} });
  const [err, setErr] = useState("");

  const get = useCallback(
    async (path) => {
      const r = await fetch(path, { headers: { Authorization: `Bearer ${token}` } });
      if (r.status === 401) throw new Error("unauthorized");
      return r.json();
    },
    [token]
  );

  useEffect(() => {
    if (!token) return;
    let stop = false;
    const tick = async () => {
      try {
        const [s, t, w, c] = await Promise.all([
          get("/api/summary"), get("/api/trades?limit=100"), get("/api/wallets"), get("/api/candidates"),
        ]);
        if (!stop) { setSum(s); setTrades(t); setWallets(w); setCands(c); setErr(""); }
      } catch (e) {
        if (e.message === "unauthorized") { localStorage.removeItem("dash_token"); setToken(""); }
        else setErr("Can't reach server");
      }
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => { stop = true; clearInterval(id); };
  }, [token, get]);

  if (!token) return <Login onToken={(t) => { localStorage.setItem("dash_token", t); setToken(t); }} />;
  if (!sum) return <div className="min-h-screen grid place-items-center text-slate-400">Loading…</div>;

  const cfg = sum.config;
  return (
    <div className="min-h-screen text-slate-100">
      <div className="mx-auto max-w-7xl p-4 space-y-4">
        <header className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-semibold">pump.fun Paper Scanner</h1>
            <span className="rounded-full bg-amber-500/15 text-amber-300 text-xs px-2 py-0.5">PAPER MODE</span>
          </div>
          <div className="text-xs text-slate-400">
            {err ? <span className="text-rose-400">{err}</span> : <>● {sum.status.phase}</>}
          </div>
        </header>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Card label="Total PnL (SOL)" value={sol(sum.total_pnl)} cls={tone(sum.total_pnl)} sub={`${sum.closed} closed trades`} />
          <Card label="Win rate" value={pct(sum.win_rate)} sub={`best ${sol(sum.best)} · worst ${sol(sum.worst)}`} />
          <Card label="Open positions" value={`${sum.open.length}/${cfg.max_open_positions}`} sub={`size ${cfg.size_sol} SOL each`} />
          <Card label="Skipped signals" value={sum.skipped} sub={`chase cap ${pct(cfg.max_chase_pct)}`} />
        </div>

        {sum.lesson && (
          <div className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-3 text-sm text-slate-300">
            <span className="text-xs uppercase tracking-wide text-slate-500">Agent read</span>
            <div className="mt-1">{sum.lesson.text}</div>
          </div>
        )}

        <Panel title="Possible entries" right={
          <span className="text-xs text-slate-500">
            {Object.entries(cands.sources || {}).map(([name, src]) => (
              <span key={name} className={`ml-2 ${src.ok ? "text-emerald-400" : "text-amber-400"}`}>
                {name}{src.ok ? ` ${src.n}` : ""}
              </span>
            ))}
          </span>
        }>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr>{["Token", "Score", "Call", "Suggestion", "Sources", "Mcap", "Liq", "5m"].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody>
              {(cands.candidates || []).length === 0 && <tr><td colSpan="8" className="px-4 py-6 text-slate-500">First scan still running.</td></tr>}
              {(cands.candidates || []).slice(0, 12).map((c) => (
                <tr key={c.mint} className="border-t border-slate-800">
                  <td className="px-4 py-2">
                    <a className="text-sky-400 hover:underline" target="_blank" rel="noreferrer" href={`https://dexscreener.com/solana/${c.mint}`}>{c.symbol || short(c.mint)}</a>
                  </td>
                  <td className="px-4 py-2 font-medium">{c.score}</td>
                  <td className={`px-4 py-2 text-xs font-semibold ${c.decision === "enter" ? "text-emerald-400" : c.decision === "skip" ? "text-slate-500" : "text-amber-300"}`}>{c.decision}</td>
                  <td className="px-4 py-2 min-w-52"><Suggestion advice={c.advice} /></td>
                  <td className="px-4 py-2 text-xs text-slate-400">{(c.sources || []).join(", ")}</td>
                  <td className="px-4 py-2 text-slate-400">{c.mcap ? `$${(c.mcap / 1000).toFixed(0)}k` : "–"}</td>
                  <td className="px-4 py-2 text-slate-400">{c.liq ? `$${(c.liq / 1000).toFixed(0)}k` : "–"}</td>
                  <td className={`px-4 py-2 ${tone(c.change_5m)}`}>{c.change_5m == null ? "–" : `${c.change_5m}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="Cumulative PnL (closed positions)">
          <Spark data={sum.cum_pnl} />
        </Panel>

        <Panel title={`Open positions`}>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr>{["Token", "Source", "Multiple", "Left", "Realized", "Age", "Suggestion"].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody>
              {sum.open.length === 0 && <tr><td colSpan="7" className="px-4 py-6 text-slate-500">No open positions.</td></tr>}
              {sum.open.map((p) => (
                <tr key={p.mint} className="border-t border-slate-800">
                  <td className="px-4 py-2"><a className="text-sky-400 hover:underline" target="_blank" rel="noreferrer" href={`https://dexscreener.com/solana/${p.mint}`}>{p.symbol || short(p.mint)}</a></td>
                  <td className="px-4 py-2 text-slate-400">{short(p.wallet)}</td>
                  <td className={`px-4 py-2 font-medium ${p.x >= 1 ? "text-emerald-400" : "text-rose-400"}`}>{p.x ? `${p.x.toFixed(2)}X` : "–"}</td>
                  <td className="px-4 py-2">{pct(p.left)}</td>
                  <td className={`px-4 py-2 ${tone(p.pnl)}`}>{sol(p.pnl)}</td>
                  <td className="px-4 py-2 text-slate-400">{p.age_min.toFixed(0)}m</td>
                  <td className="px-4 py-2 min-w-52"><Suggestion advice={p.advice} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <div className="grid md:grid-cols-2 gap-4">
          <Panel title="Recent activity">
            <table className="w-full text-sm">
              <tbody>
                {trades.length === 0 && <tr><td className="px-4 py-6 text-slate-500">No activity yet.</td></tr>}
                {trades.slice(0, 40).map((t, i) => (
                  <tr key={i} className="border-t border-slate-800 first:border-0">
                    <td className="px-4 py-2 text-xs text-slate-500 whitespace-nowrap">{t.time.slice(5, 16)}</td>
                    <td className={`px-2 py-2 text-xs font-semibold ${t.event === "BUY" ? "text-sky-400" : t.event === "SELL" ? "text-emerald-400" : t.event === "CLOSED" ? "text-violet-400" : "text-slate-500"}`}>{t.event}</td>
                    <td className="px-2 py-2 text-slate-300">{short(t.mint)}</td>
                    <td className="px-2 py-2 text-slate-400">{Number(t.x) ? `${t.x}X` : ""}</td>
                    <td className={`px-2 py-2 ${tone(Number(t.sol_pnl))}`}>{Number(t.sol_pnl) ? sol(Number(t.sol_pnl)) : ""}</td>
                    <td className="px-2 py-2 text-xs text-slate-500">{t.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel title="Tracked wallets">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-slate-500">
                <tr>{["Wallet", "PnL", "Win", "Trades", "Hold"].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}</tr>
              </thead>
              <tbody>
                {wallets.length === 0 && <tr><td colSpan="5" className="px-4 py-6 text-slate-500">No wallets ranked yet.</td></tr>}
                {wallets.map((w) => (
                  <tr key={w.wallet} className="border-t border-slate-800">
                    <td className="px-4 py-2"><a className="text-sky-400 hover:underline" target="_blank" rel="noreferrer" href={`https://solscan.io/account/${w.wallet}`}>{short(w.wallet)}</a></td>
                    <td className={`px-4 py-2 ${tone(w.pnl_sol)}`}>{sol(w.pnl_sol)}</td>
                    <td className="px-4 py-2">{pct(w.win_rate)}</td>
                    <td className="px-4 py-2">{w.trades}</td>
                    <td className="px-4 py-2 text-slate-400">{Math.round(w.median_hold)}s</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </div>

        <footer className="text-xs text-slate-600 pb-6">
          Ladder: {cfg.ladder.map((l) => `${l.x}X`).join(" → ")} · stop-loss −{pct(cfg.stop_loss_pct)}. Simulated results only.
        </footer>
      </div>
    </div>
  );
}
