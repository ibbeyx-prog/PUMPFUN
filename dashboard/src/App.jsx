import { useEffect, useState, useCallback } from "react";
import PhantomLink from "./Phantom.jsx";
import EyeDesk, { EyeFloor } from "./EyeDesk.jsx";

const short = (s) => (!s ? "" : s.length > 20 ? `${s.slice(0, 4)}…${s.slice(-4)}` : s);
const usd = (n) => {
  if (n == null) return null;
  const abs = Math.abs(n);
  const body = abs >= 100 ? abs.toFixed(0) : abs.toFixed(2);
  return `${n < 0 ? "-" : "+"}$${Number(body).toLocaleString()}`;
};
const dollars = (n, signed = false) => {
  if (n == null) return "–";
  const num = Number(n);
  if (Number.isNaN(num)) return "–";
  const abs = Math.abs(num);
  const body = abs >= 100 ? abs.toFixed(0) : abs.toFixed(2);
  const text = `$${Number(body).toLocaleString()}`;
  return signed ? `${num < 0 ? "-" : "+"}${text}` : text;
};
const pct = (n) => (n == null ? "–" : `${(n * 100).toFixed(0)}%`);
const solToUsd = (solAmount, px) => {
  const n = Number(solAmount);
  const price = Number(px);
  if (!price || Number.isNaN(n)) return null;
  return n * price;
};
const tone = (n) => (n > 0 ? "text-emerald-300" : n < 0 ? "text-rose-300" : "text-slate-400");
const when = (s) => (s ? String(s).replace("T", " ").replace("Z", "").slice(5, 16) : "");
const bubbleMapUrl = (c) => {
  const raw = c.bubble_url || `https://v2.bubblemaps.io/map?address=${c.mint}&chain=solana`;
  try {
    const url = new URL(raw);
    const chain = url.searchParams.get("chain");
    if (!chain || chain === "sol") url.searchParams.set("chain", "solana");
    if (!url.searchParams.get("address") && c.mint) url.searchParams.set("address", c.mint);
    return url.toString();
  } catch {
    return raw;
  }
};
const adviceTone = (label) =>
  ["Take", "Hold", "Sell", "Let winners run", "Keep the book"].includes(label) ? "text-emerald-300" : ["Cut", "Pass", "Skip", "Cut fades", "Skip one source"].includes(label) ? "text-rose-300" : "text-amber-200";

function ChatDock({ token }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    let stop = false;
    fetch("/api/chat", { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.json())
      .then((d) => { if (!stop) setMessages(d.messages || []); })
      .catch(() => {});
    return () => { stop = true; };
  }, [open, token]);

  async function send(e) {
    e.preventDefault();
    const message = text.trim();
    if (!message || busy) return;
    setText("");
    setBusy(true);
    setMessages((m) => [...m, { role: "user", text: message, time: "" }]);
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });
      const d = await r.json();
      if (r.ok) setMessages(d.messages || []);
      else setMessages((m) => [...m, { role: "agent", text: "I couldn't answer that.", time: "" }]);
    } catch {
      setMessages((m) => [...m, { role: "agent", text: "Can't reach the agent.", time: "" }]);
    }
    setBusy(false);
  }

  return (
    <div className="fixed bottom-4 right-4 z-30 w-[min(24rem,calc(100vw-2rem))]">
      {open && (
        <div className="mb-2 flex h-[30rem] flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#10131a] shadow-2xl shadow-black/50">
          <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
            <div>
              <div className="text-sm font-medium">Agent</div>
              <div className="text-[11px] text-slate-500">PnL, positions, the 24h report, or a token</div>
            </div>
            <span className="h-2 w-2 rounded-full bg-emerald-400" />
          </div>
          <div className="flex-1 space-y-3 overflow-y-auto p-4 text-sm">
            {messages.length === 0 && <div className="text-slate-500">Ask about PnL, open positions, the 24h report, or a token.</div>}
            {messages.map((m, i) => (
              <div key={i} className={m.role === "user" ? "text-right" : ""}>
                <div className={`inline-block max-w-[90%] rounded-2xl px-3 py-2 text-left ${m.role === "user" ? "bg-amber-400 text-slate-950" : "bg-white/[0.06] text-slate-200"}`}>
                  {m.text}
                </div>
              </div>
            ))}
          </div>
          <form onSubmit={send} className="flex gap-2 border-t border-white/10 p-3">
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Ask the agent"
              className="flex-1 rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none focus:border-amber-400/60"
            />
            <button disabled={busy} className="rounded-xl bg-amber-400 px-3 py-2 text-sm font-medium text-slate-950 disabled:opacity-50">Send</button>
          </form>
        </div>
      )}
      <div className="flex justify-end">
        <button onClick={() => setOpen((v) => !v)} className="rounded-full border border-amber-300/30 bg-[#1a160e] px-4 py-2 text-sm font-medium text-amber-100 shadow-lg hover:bg-amber-400/15">
          {open ? "Close chat" : "Chat"}
        </button>
      </div>
    </div>
  );
}

function Suggestion({ advice }) {
  if (!advice) return <span className="text-slate-600">–</span>;
  return (
    <div>
      <div className={`text-xs font-semibold ${adviceTone(advice.label)}`}>{advice.label}</div>
      <div className="text-xs text-slate-500">{advice.text}</div>
    </div>
  );
}

function Shell({ title, hint, children }) {
  return (
    <section className="overflow-hidden rounded-2xl border border-white/[0.07] bg-[#141820]/90">
      {(title || hint) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/[0.06] px-4 py-3">
          {title && <h2 className="text-sm font-medium text-slate-200">{title}</h2>}
          {hint}
        </div>
      )}
      <div className="overflow-x-auto">{children}</div>
    </section>
  );
}

function Spark({ data }) {
  if (!data || data.length < 2)
    return <div className="px-1 py-6 text-sm text-slate-500">Not enough closed trades yet.</div>;
  const w = 640, h = 140, min = Math.min(0, ...data), max = Math.max(0, ...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / span) * h}`);
  const zero = h - ((0 - min) / span) * h;
  const up = data[data.length - 1] >= 0;
  const color = up ? "#6ee7b7" : "#fda4af";
  const area = `0,${h} ${pts.join(" ")} ${w},${h}`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-32 w-full" preserveAspectRatio="none">
      <line x1="0" x2={w} y1={zero} y2={zero} stroke="rgba(255,255,255,0.12)" strokeDasharray="4" />
      <polygon points={area} fill={color} opacity="0.12" />
      <polyline fill="none" strokeWidth="2.5" stroke={color} points={pts.join(" ")} />
    </svg>
  );
}

function Th({ children }) {
  return <th className="px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-[0.12em] text-slate-500">{children}</th>;
}

function Empty({ cols, children }) {
  return <tr><td colSpan={cols} className="px-4 py-8 text-sm text-slate-500">{children}</td></tr>;
}

function Login({ onToken }) {
  const [v, setV] = useState("");
  return (
    <div className="grid min-h-screen place-items-center px-4">
      <form
        className="w-full max-w-sm rounded-2xl border border-white/10 bg-[#141820] p-6"
        onSubmit={(e) => { e.preventDefault(); onToken(v); }}
      >
        <div className="mb-1 text-[11px] uppercase tracking-[0.16em] text-amber-300">Paper mode</div>
        <h1 className="text-2xl font-semibold">Paper Scanner</h1>
        <p className="mt-1 text-sm text-slate-500">Simulated pump.fun entries. Nothing is sent on-chain.</p>
        <input
          type="password"
          value={v}
          onChange={(e) => setV(e.target.value)}
          placeholder="Dashboard token"
          className="mt-5 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 outline-none focus:border-amber-400/70"
        />
        <button className="mt-3 w-full rounded-xl bg-amber-400 py-2.5 font-medium text-slate-950 hover:bg-amber-300">
          Enter
        </button>
      </form>
    </div>
  );
}

const TABS = [
  ["scan", "Scan"],
  ["book", "Book"],
  ["reports", "Reports"],
  ["agent", "Agent"],
];

export default function App() {
  const [token, setToken] = useState(localStorage.getItem("dash_token") || "");
  const [sum, setSum] = useState(null);
  const [trades, setTrades] = useState([]);
  const [wallets, setWallets] = useState([]);
  const [cands, setCands] = useState({ candidates: [], sources: {} });
  const [eye, setEye] = useState({ knowledge: [] });
  const [err, setErr] = useState("");
  const [tab, setTab] = useState("scan");

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
        const [s, t, w, c, e] = await Promise.all([
          get("/api/summary"), get("/api/trades?limit=100"), get("/api/wallets"), get("/api/candidates"), get("/api/eye"),
        ]);
        if (!stop) { setSum(s); setTrades(t); setWallets(w); setCands(c); setEye(e); setErr(""); }
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
  if (!sum) return <div className="grid min-h-screen place-items-center text-slate-500">Loading…</div>;

  const cfg = sum.config;
  const px = sum.sol_usd || sum.budget?.sol_usd;
  const pnlUsd = (solAmount) => usd(solToUsd(solAmount, px));
  const equity = sum.budget?.equity_usd;
  const started = sum.budget?.start_usd;
  const budget = [
    ["Start", dollars(sum.budget?.start_usd)],
    ["Equity", dollars(equity)],
    ["Realized", dollars(sum.budget?.realized_usd, true)],
    ["In trades", dollars(sum.budget?.deployed_usd)],
    ["Free to invest", dollars(sum.budget?.available_usd)],
    ["Reserve", dollars(sum.budget?.reserve_usd)],
    ["SOL price", sum.budget?.sol_usd ? `$${sum.budget.sol_usd}` : "–"],
  ];

  return (
    <div className="min-h-screen pb-24">
      <header className="sticky top-0 z-20 border-b border-white/[0.06] bg-[#0c0e13] shadow-[0_12px_30px_rgba(0,0,0,0.45)]">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="grid h-9 w-9 place-items-center rounded-xl bg-amber-400 text-sm font-semibold text-slate-950">P</div>
            <div>
              <h1 className="text-base font-semibold leading-tight">Paper Scanner</h1>
              <div className="text-[11px] text-slate-500">pump.fun · simulated book</div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="rounded-full border border-amber-300/30 bg-amber-400/10 px-2.5 py-1 text-amber-200">PAPER MODE</span>
            <PhantomLink token={token} />
            <span className={`rounded-full border border-white/10 px-2.5 py-1 ${err ? "text-rose-300" : "text-slate-300"}`}>
              {err || `● ${sum.status.phase}`}
            </span>
            {sum.sol_usd && <span className="num rounded-full border border-white/10 px-2.5 py-1 text-slate-300">SOL ${sum.sol_usd}</span>}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-4 px-4 py-5">
        <section className="grid grid-cols-2 gap-2 md:grid-cols-4">
          {(sum.desk?.roles || []).map((role) => (
            <div key={role.id} className="rounded-2xl border border-white/[0.07] bg-[#141820]/90 px-3 py-3">
              <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">{role.name}</div>
              <div className="num mt-1 truncate text-lg text-slate-100">{role.value}</div>
              <div className="mt-1 text-xs text-slate-500">{role.sub}</div>
            </div>
          ))}
        </section>

        <EyeFloor
          eye={eye}
          phase={sum.status?.phase}
          pick={(sum.desk?.roles || []).find((role) => role.id === "chief")?.value}
        />

        <section className="rounded-2xl border border-white/[0.07] bg-[#141820]/90 p-4">
          <div className="mb-3 text-sm font-medium text-slate-200">Meme-coin feeds</div>
          <div className="flex flex-wrap gap-2">
            {(sum.desk?.feeds || []).map((feed) => (
              <span key={feed.name} className={`rounded-full px-2.5 py-1 text-xs ${feed.state === "live" || feed.state === "ready" || feed.state === "link" ? "bg-emerald-400/10 text-emerald-200" : feed.state === "key" || feed.state === "down" ? "bg-amber-400/10 text-amber-200" : "bg-white/5 text-slate-500"}`}>
                {feed.name}
                <span className="ml-1 text-[10px] uppercase tracking-wide opacity-70">{feed.state}</span>
              </span>
            ))}
          </div>
        </section>

        <section className="grid gap-3 lg:grid-cols-5">
          <div className="rounded-2xl border border-white/[0.07] bg-[#141820]/90 p-5 lg:col-span-3">
            <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">Total PnL</div>
            <div className={`num mt-2 text-4xl font-medium ${equity == null || started == null ? "text-slate-100" : tone(equity - started)}`}>
              {dollars(equity)}
            </div>
            <div className="mt-1 text-sm text-slate-400">current equity</div>
            <div className="mt-2 text-xs text-slate-500">
              realized {dollars(sum.budget?.realized_usd, true)}
              {sum.budget?.realized_sol != null ? ` · ${Number(sum.budget.realized_sol).toFixed(3)} SOL` : ""} · {sum.closed} closed trades
            </div>
            <div className="mt-4">
              <Spark data={sum.cum_pnl} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 lg:col-span-2">
            {[
              ["Win rate", pct(sum.win_rate), `best ${pnlUsd(sum.best) || "–"} · worst ${pnlUsd(sum.worst) || "–"}`],
              ["Open", `${sum.open.length}/${cfg.max_open_positions}`, `$${sum.budget?.trade_usd ?? cfg.trade_usd} per trade · one per coin`],
              ["Skipped", sum.skipped, `chase cap ${pct(cfg.max_chase_pct)}`],
              ["Closed PnL", pnlUsd(sum.total_pnl) || "–", `${sum.total_pnl == null ? "–" : Number(sum.total_pnl).toFixed(3)} SOL · ${sum.closed} closed`],
            ].map(([label, value, sub]) => (
              <div key={label} className="rounded-2xl border border-white/[0.07] bg-[#141820]/90 p-4">
                <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">{label}</div>
                <div className="num mt-2 text-2xl text-slate-100">{value}</div>
                <div className="mt-1 text-xs text-slate-500">{sub}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-2xl border border-white/[0.07] bg-[#141820]/90 p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-medium text-slate-200">Budget</h2>
            <span className="text-xs text-slate-500">{sum.budget?.sol_usd ? `SOL $${sum.budget.sol_usd}` : ""}</span>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
            {budget.map(([label, value]) => (
              <div key={label} className={`rounded-xl px-3 py-2 ${label === "Free to invest" ? "bg-amber-400/10 ring-1 ring-amber-300/25" : "bg-black/20"}`}>
                <div className="text-[11px] uppercase tracking-[0.12em] text-slate-500">{label}</div>
                <div className="num mt-1 text-base text-slate-100">{value}</div>
              </div>
            ))}
          </div>
        </section>

        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-300/20 bg-amber-400/[0.07] px-4 py-3 text-sm">
          <span className="font-medium text-amber-200">paper only</span>
          <span className="text-amber-100/80">{sum.live?.wallet_trade ? "Wallet trading is on. Each buy still needs the lock code and a Phantom approval." : `Paper buys are sized like a Phantom swap. Eye picks the amount, and $${sum.budget?.reserve_usd ?? cfg.reserve_usd} stays in the wallet for fees.`}</span>
        </div>

        {(() => {
          const age = sum.scan?.at ? Date.now() / 1000 - sum.scan.at : null;
          const down = (sum.desk?.feeds || []).filter((feed) => feed.state === "down").map((feed) => feed.name);
          if ((age == null || age <= 300) && down.length === 0) return null;
          return (
            <div className="rounded-2xl border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">
              {age != null && age > 300 ? `Scan has not finished for ${Math.round(age / 60)} minutes. ` : ""}
              {down.length ? `Feeds down: ${down.join(", ")}.` : ""}
            </div>
          );
        })()}

        <nav className="flex gap-1 rounded-2xl border border-white/[0.07] bg-[#141820]/70 p-1">
          {TABS.map(([id, label]) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`flex-1 rounded-xl px-3 py-2 text-sm ${tab === id ? "bg-white text-slate-950" : "text-slate-400 hover:text-slate-200"}`}
            >
              {label}
              {id === "book" && sum.open.length > 0 ? ` ${sum.open.length}` : ""}
            </button>
          ))}
        </nav>

        {tab === "scan" && (
          <Shell
            title="Possible entries"
            hint={
              <span className="flex flex-wrap gap-1.5 text-xs">
                {Object.entries(cands.sources || {}).map(([name, src]) => (
                  <span key={name} className={`rounded-full px-2 py-0.5 ${src.ok ? "bg-emerald-400/10 text-emerald-300" : "bg-amber-400/10 text-amber-200"}`}>
                    {name}{src.ok ? ` ${src.n}` : ""}
                  </span>
                ))}
              </span>
            }
          >
            <table className="w-full text-sm">
              <thead>
                <tr>{["Token", "Score", "Call", "Suggestion", "Eye", "Sources", "Mcap", "Liq", "5m", "Rug", "Map"].map((h) => <Th key={h}>{h}</Th>)}</tr>
              </thead>
              <tbody>
                {(cands.candidates || []).length === 0 && <Empty cols={11}>First scan still running.</Empty>}
                {(cands.candidates || []).slice(0, 12).map((c) => (
                  <tr key={c.mint} className="border-t border-white/[0.05] hover:bg-white/[0.03]">
                    <td className="px-4 py-2.5">
                      <a className="text-sky-300 hover:underline" target="_blank" rel="noreferrer" href={`https://dexscreener.com/solana/${c.mint}`}>{c.symbol || short(c.mint)}</a>
                    </td>
                    <td className="num px-4 py-2.5">{c.score}</td>
                    <td className="px-4 py-2.5">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${c.decision === "enter" ? "bg-emerald-400/15 text-emerald-300" : c.decision === "skip" ? "bg-white/5 text-slate-500" : "bg-amber-400/15 text-amber-200"}`}>{c.decision}</span>
                    </td>
                    <td className="min-w-52 px-4 py-2.5"><Suggestion advice={c.advice} /></td>
                    <td className="min-w-52 px-4 py-2.5"><Suggestion advice={c.eye} /></td>
                    <td className="px-4 py-2.5 text-xs text-slate-400">{(c.sources || []).join(", ")}</td>
                    <td className="num px-4 py-2.5 text-slate-400">{c.mcap ? `$${(c.mcap / 1000).toFixed(0)}k` : "–"}</td>
                    <td className="num px-4 py-2.5 text-slate-400">{c.liq ? `$${(c.liq / 1000).toFixed(0)}k` : "–"}</td>
                    <td className={`num px-4 py-2.5 ${tone(c.change_5m)}`}>{c.change_5m == null ? "–" : `${c.change_5m}%`}</td>
                    <td className="px-4 py-2.5 text-xs">
                      {c.rug_score == null && !c.rug_label ? "–" : (
                        <a className={c.rug_label && c.rug_label !== "clean" ? "text-rose-300 hover:underline" : "text-emerald-300 hover:underline"} target="_blank" rel="noreferrer" href={`https://rugcheck.xyz/tokens/${c.mint}`}>
                          {c.rug_label && c.rug_label !== "clean" ? c.rug_label : `clean ${c.rug_score ?? ""}`}
                        </a>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-xs">
                      <a className="text-sky-300 hover:underline" target="_blank" rel="noreferrer" href={bubbleMapUrl(c)}>
                        {c.bubble_cluster != null ? `${Math.round(c.bubble_cluster * 100)}%` : (c.bubble_label || "map")}
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Shell>
        )}

        {tab === "book" && (
          <div className="space-y-4">
            <Shell title="Open positions">
              <table className="w-full text-sm">
                <thead>
                  <tr>{["Token", "Source", "Multiple", "Left", "Realized", "Cost", "Age", "Suggestion", "Eye"].map((h) => <Th key={h}>{h}</Th>)}</tr>
                </thead>
                <tbody>
                  {sum.open.length === 0 && <Empty cols={9}>No open positions.</Empty>}
                  {sum.open.map((p) => (
                    <tr key={p.mint} className="border-t border-white/[0.05] hover:bg-white/[0.03]">
                      <td className="px-4 py-2.5"><a className="text-sky-300 hover:underline" target="_blank" rel="noreferrer" href={`https://dexscreener.com/solana/${p.mint}`}>{p.symbol || short(p.mint)}</a></td>
                      <td className="px-4 py-2.5 text-slate-400">{short(p.wallet)}</td>
                      <td className={`num px-4 py-2.5 font-medium ${p.x >= 1 ? "text-emerald-300" : "text-rose-300"}`}>{p.x ? `${p.x.toFixed(2)}X` : "–"}</td>
                      <td className="num px-4 py-2.5">{pct(p.left)}</td>
                      <td className={`num px-4 py-2.5 ${tone(p.pnl)}`}>{pnlUsd(p.pnl) || "–"}</td>
                      <td className="num px-4 py-2.5 text-slate-400">{p.cost_usd != null ? `$${Number(p.cost_usd).toFixed(2)}` : "–"}</td>
                      <td className="num px-4 py-2.5 text-slate-400">{p.age_min.toFixed(0)}m</td>
                      <td className="min-w-52 px-4 py-2.5"><Suggestion advice={p.advice} /></td>
                      <td className="min-w-52 px-4 py-2.5"><Suggestion advice={p.eye} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Shell>

            <div className="grid gap-4 lg:grid-cols-2">
              <Shell title="Recent activity">
                <table className="w-full text-sm">
                  <thead>
                    <tr>{["Time", "Event", "Token", "Multiple", "PnL", "Note", "Eye"].map((h) => <Th key={h}>{h}</Th>)}</tr>
                  </thead>
                  <tbody>
                    {trades.length === 0 && <Empty cols={7}>No activity yet.</Empty>}
                    {trades.slice(0, 40).map((t, i) => (
                      <tr key={i} className="border-t border-white/[0.05] hover:bg-white/[0.03]">
                        <td className="num whitespace-nowrap px-4 py-2 text-xs text-slate-500">{when(t.time)}</td>
                        <td className={`px-2 py-2 text-xs font-semibold ${t.event === "BUY" ? "text-sky-300" : t.event === "SELL" ? "text-emerald-300" : t.event === "CLOSED" ? "text-violet-300" : "text-slate-500"}`}>{t.event}</td>
                        <td className="px-2 py-2 text-slate-300">{short(t.mint)}</td>
                        <td className="num px-2 py-2 text-slate-400">{Number(t.x) ? `${t.x}X` : ""}</td>
                        <td className={`num px-2 py-2 ${tone(Number(t.sol_pnl))}`}>{Number(t.sol_pnl) ? pnlUsd(t.sol_pnl) : ""}</td>
                        <td className="px-2 py-2 text-xs text-slate-500">{t.note}</td>
                        <td className="min-w-52 px-4 py-2"><Suggestion advice={t.eye} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Shell>

              <Shell title="Tracked wallets">
                <table className="w-full text-sm">
                  <thead>
                    <tr>{["Wallet", "PnL", "Win", "Trades", "Hold"].map((h) => <Th key={h}>{h}</Th>)}</tr>
                  </thead>
                  <tbody>
                    {wallets.length === 0 && <Empty cols={5}>No wallets ranked yet.</Empty>}
                    {wallets.map((w) => (
                      <tr key={w.wallet} className="border-t border-white/[0.05] hover:bg-white/[0.03]">
                        <td className="px-4 py-2.5"><a className="text-sky-300 hover:underline" target="_blank" rel="noreferrer" href={`https://solscan.io/account/${w.wallet}`}>{short(w.wallet)}</a></td>
                        <td className={`num px-4 py-2.5 ${tone(w.pnl_sol)}`}>{pnlUsd(w.pnl_sol) || "–"}</td>
                        <td className="num px-4 py-2.5">{pct(w.win_rate)}</td>
                        <td className="num px-4 py-2.5">{w.trades}</td>
                        <td className="num px-4 py-2.5 text-slate-400">{Math.round(w.median_hold)}s</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Shell>
            </div>
          </div>
        )}

        {tab === "reports" && (
          <Shell
            title="24h reports"
            hint={<span className="text-xs text-slate-500">{sum.reports ? `next in ${sum.reports.next_in_h}h · ${sum.reports.next_at}` : ""}</span>}
          >
            <table className="w-full text-sm">
              <thead>
                <tr>{["Window", "Closed", "Win", "PnL", "Buys", "Report"].map((h) => <Th key={h}>{h}</Th>)}</tr>
              </thead>
              <tbody>
                {(sum.reports?.reports || []).length === 0 && (
                  <Empty cols={6}>The first report is written when 24 hours have passed. Next one {sum.reports?.next_at || "soon"}.</Empty>
                )}
                {(sum.reports?.reports || []).map((r) => (
                  <tr key={r.start} className="border-t border-white/[0.05] hover:bg-white/[0.03]">
                    <td className="num whitespace-nowrap px-4 py-2.5 text-xs text-slate-400">{when(r.start)} → {when(r.end)}</td>
                    <td className="num px-4 py-2.5">{r.closed}</td>
                    <td className="num px-4 py-2.5">{pct(r.win_rate)}</td>
                    <td className={`num px-4 py-2.5 ${tone(r.pnl)}`}>{pnlUsd(r.pnl) || "–"}</td>
                    <td className="num px-4 py-2.5 text-slate-400">{r.buys}</td>
                    <td className="px-4 py-2.5 text-xs text-slate-300">{r.text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Shell>
        )}

        {tab === "agent" && (
          <div className="space-y-4">
            <EyeDesk eye={eye} phase={sum.status?.phase} />
            {sum.lesson && (
              <div className="rounded-2xl border border-white/[0.07] bg-[#141820]/90 px-4 py-3 text-sm text-slate-300">
                <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">Agent read</div>
                <div className="mt-1">{sum.lesson.text}</div>
              </div>
            )}

            <Shell title="Skills" hint={<span className="text-xs text-slate-500">{sum.skills?.updated ? `studied ${sum.skills.updated.slice(11, 16)}` : "waiting for a scan"}</span>}>
              <div className="px-4 py-3 text-sm text-slate-300">{sum.skills?.note || "The agent studies the next scan before it buys."}</div>
              <table className="w-full text-sm">
                <thead>
                  <tr>{["Skill", "How it trades", "Learned from"].map((h) => <Th key={h}>{h}</Th>)}</tr>
                </thead>
                <tbody>
                  {(sum.skills?.skills || []).map((s) => (
                    <tr key={s.id} className="border-t border-white/[0.05]">
                      <td className="whitespace-nowrap px-4 py-2.5 text-slate-200">{s.name}</td>
                      <td className="px-4 py-2.5 text-slate-300">{s.lesson}</td>
                      <td className="px-4 py-2.5 text-xs text-slate-500">{s.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Shell>

            <Shell title="Eye">
              <div className="px-4 py-3 text-[11px] uppercase tracking-[0.14em] text-slate-500">How Eye is growing</div>
              <div className="divide-y divide-white/[0.05]">
                {(eye.growth || []).length === 0 && <div className="px-4 py-4 text-sm text-slate-500">The first growth pass runs after Eye checks the public market.</div>}
                {(eye.growth || []).map((g, i) => (
                  <div key={i} className="px-4 py-3 text-sm">
                    <div className="text-slate-200">{g.did}</div>
                    <div className="mt-1 text-xs text-slate-500">
                      {when(g.time)}
                      {g.win_rate != null ? ` · last closes ${Math.round(g.win_rate * 100)}% won` : ""}
                      {g.equity_usd != null ? ` · equity $${g.equity_usd}` : ""}
                    </div>
                  </div>
                ))}
              </div>
              <div className="px-4 py-3 text-[11px] uppercase tracking-[0.14em] text-slate-500">How to trade better</div>
              <div className="divide-y divide-white/[0.05]">
                {(eye.improvements || []).length === 0 && <div className="px-4 py-4 text-sm text-slate-500">No recommendation yet.</div>}
                {(eye.improvements || []).map((n) => (
                  <div key={n.id} className="px-4 py-3 text-sm">
                    <span className={`mr-2 text-xs font-semibold ${adviceTone(n.label)}`}>{n.label}</span>
                    <span className="text-slate-200">{n.text}</span>
                  </div>
                ))}
              </div>
              <div className="px-4 py-3 text-[11px] uppercase tracking-[0.14em] text-slate-500">What Eye has learned</div>
              <div className="divide-y divide-white/[0.05]">
                {(eye.knowledge || []).length === 0 && <div className="px-4 py-4 text-sm text-slate-500">No notes yet. Eye writes them after a research pass or a review.</div>}
                {(eye.knowledge || []).map((n, i) => (
                  <div key={i} className="px-4 py-3 text-sm">
                    <span className={`mr-2 rounded-full px-2 py-0.5 text-xs ${n.src === "web" ? "bg-sky-400/15 text-sky-300" : "bg-amber-400/15 text-amber-200"}`}>
                      {n.src === "web" ? "market" : "own trades"}
                    </span>
                    <span className="text-slate-200">{n.text}</span>
                  </div>
                ))}
              </div>
            </Shell>

            <Shell
              title="Agent changes"
              hint={
                <span className="text-xs text-slate-500">
                  {sum.agent && sum.agent.values && Object.entries(sum.agent.values).map(([k, v]) => (
                    <span key={k} className="ml-2">{k} {String(v)}</span>
                  ))}
                </span>
              }
            >
              <table className="w-full text-sm">
                <thead>
                  <tr>{["Time", "Change", "From", "To", "Why"].map((h) => <Th key={h}>{h}</Th>)}</tr>
                </thead>
                <tbody>
                  {(sum.agent?.changes || []).length === 0 && <Empty cols={5}>No edits yet. Eye waits for 30 closed trades before it changes a rule.</Empty>}
                  {(sum.agent?.changes || []).map((c, i) => (
                    <tr key={i} className="border-t border-white/[0.05]">
                      <td className="num whitespace-nowrap px-4 py-2.5 text-xs text-slate-500">{when(c.time)}</td>
                      <td className="px-4 py-2.5 text-slate-200">{c.what}</td>
                      <td className="px-4 py-2.5 text-slate-400">{c.from || "–"}</td>
                      <td className="px-4 py-2.5 text-emerald-300">{c.to}</td>
                      <td className="px-4 py-2.5 text-xs text-slate-500">{c.why}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Shell>
          </div>
        )}

        <footer className="text-xs text-slate-600">
          Ladder: {cfg.ladder.map((l) => `${l.x}X`).join(" → ")} · stop-loss −{pct(cfg.stop_loss_pct)}. Simulated results only.
        </footer>
      </main>
      <ChatDock token={token} />
    </div>
  );
}
