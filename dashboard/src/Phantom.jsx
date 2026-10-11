import { useEffect, useRef, useState } from "react";
import { VersionedTransaction } from "@solana/web3.js";

const short = (s) => (!s ? "" : s.length > 12 ? `${s.slice(0, 4)}…${s.slice(-4)}` : s);

function provider() {
  const sol = window.phantom?.solana || window.solana;
  return sol?.isPhantom ? sol : null;
}

function fromBase64(value) {
  const bin = atob(value);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
  return out;
}

export default function PhantomLink({ token }) {
  const [info, setInfo] = useState(null);
  const [note, setNote] = useState("");
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const signing = useRef(false);

  async function call(path, body) {
    const r = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok && data.error) setNote(data.error);
    return data;
  }

  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const data = await call("/api/phantom");
        if (!stop) setInfo(data);
      } catch {
        if (!stop) setNote("Can't reach the wallet link.");
      }
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => { stop = true; clearInterval(id); };
  }, [token]);

  async function connect() {
    const phantom = provider();
    if (!phantom) {
      setNote("Install the Phantom extension, then refresh this page.");
      return;
    }
    setBusy(true);
    try {
      const res = await phantom.connect();
      const address = res.publicKey.toString();
      const next = await call("/api/phantom", { address, trade: false });
      setInfo(next);
      setNote("Phantom is connected. Set a lock code, then allow trades.");
    } catch (err) {
      setNote(String(err?.message || "Phantom connection was cancelled.").slice(0, 160));
    }
    setBusy(false);
  }

  async function saveLock() {
    setBusy(true);
    const next = await call("/api/phantom/lock", { pin, old: info?.locked ? pin : "" });
    if (next && !next.error) {
      setInfo(next);
      setNote("Lock code saved. It is required before any wallet buy.");
    }
    setBusy(false);
  }

  async function allow(trade) {
    if (!info?.phantom) return;
    setBusy(true);
    const next = await call("/api/phantom", { address: info.phantom, trade, pin: trade ? pin : "" });
    if (next && !next.error) {
      setInfo(next);
      setNote(trade ? "Wallet trading is on. You still approve each buy." : "Wallet trading is off.");
    }
    setBusy(false);
  }

  async function approve(order) {
    const phantom = provider();
    if (!phantom) {
      setNote("Install the Phantom extension, then refresh this page.");
      return;
    }
    const connected = phantom.publicKey?.toString();
    if (connected && connected !== info?.phantom) {
      setNote("Phantom is a different wallet than the one linked.");
      return;
    }
    if (signing.current) return;
    signing.current = true;
    setBusy(true);
    try {
      const built = await call("/api/phantom/swap", { id: order.id, pin });
      if (!built.transaction) return;
      const tx = VersionedTransaction.deserialize(fromBase64(built.transaction));
      const sent = await phantom.signAndSendTransaction(tx);
      const signature = typeof sent === "string" ? sent : sent?.signature || "";
      const next = await call("/api/phantom/done", { id: order.id, signature });
      setInfo(next);
      setNote(signature ? `Sent ${order.symbol || "buy"}` : "Phantom did not return a signature.");
    } catch (err) {
      const message = String(err?.message || err || "Phantom rejected the buy").slice(0, 160);
      const next = await call("/api/phantom/done", { id: order.id, error: message });
      setInfo(next);
      setNote(message);
    } finally {
      signing.current = false;
      setBusy(false);
    }
  }

  async function disconnect() {
    try { await provider()?.disconnect(); } catch { /* already closed */ }
    const next = await call("/api/phantom", { address: "", trade: false });
    setInfo(next);
    setNote("");
  }

  const linked = info?.phantom;
  const trading = Boolean(info?.wallet_trade);
  const pending = (info?.orders || []).find((o) => o.status === "pending");

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      {!linked && (
        <button disabled={busy} onClick={connect} className="rounded-full bg-violet-400 px-3 py-1 font-medium text-slate-950 hover:bg-violet-300 disabled:opacity-50">
          Connect Phantom
        </button>
      )}
      {linked && <span className="rounded-full border border-violet-300/40 bg-violet-400/10 px-2.5 py-1 text-violet-100">{short(linked)}</span>}
      <input
        type="password"
        value={pin}
        onChange={(e) => setPin(e.target.value)}
        placeholder={info?.locked ? "Lock code" : "Set a lock code"}
        className="w-28 rounded-full border border-white/10 bg-black/30 px-3 py-1 text-slate-100 outline-none focus:border-violet-300/60"
      />
      {!info?.locked && (
        <button disabled={busy || pin.trim().length < 4} onClick={saveLock} className="rounded-full border border-white/15 px-3 py-1 text-slate-200 disabled:opacity-40">
          Set lock
        </button>
      )}
      {linked && (
        <>
          <button disabled={busy || ( !trading && pin.trim().length < 4)} onClick={() => allow(!trading)} className={`rounded-full px-3 py-1 font-medium ${trading ? "bg-emerald-400 text-slate-950" : "border border-white/15 text-slate-200"}`}>
            {trading ? "Wallet trading on" : "Allow trades"}
          </button>
          <button onClick={disconnect} className="rounded-full border border-white/10 px-2.5 py-1 text-slate-400">Disconnect</button>
        </>
      )}
      {pending && (
        <button disabled={busy || pin.trim().length < 4} onClick={() => approve(pending)} className="rounded-full bg-amber-400 px-3 py-1 font-medium text-slate-950 disabled:opacity-40">
          Approve {pending.symbol || "buy"} ${pending.usd}
        </button>
      )}
      {note && <span className="max-w-xs text-slate-500">{note}</span>}
    </div>
  );
}
