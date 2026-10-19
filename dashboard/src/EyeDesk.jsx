const ROSTER = [
  {
    name: "Vet",
    focus: "Safety",
    task: "Checks rugs and holder maps, then tells Eye what is safe to look at.",
  },
  {
    name: "Scan watch",
    focus: "Names",
    task: "Reads the scan and puts the strongest names in front of Eye.",
  },
  {
    name: "Scout",
    focus: "Strategy",
    task: "Researches the Lab and the closed book, then tells Eye which strategy looks closest to profitable.",
  },
  {
    name: "Scribe",
    focus: "Book",
    task: "Reviews closed trades and tells Eye whether the book is paying.",
  },
  {
    name: "Risk",
    focus: "Wallet",
    task: "Watches the book and keeps the wallet off while it is losing.",
  },
];

function staffOf(eye) {
  const hired = new Map((eye?.assistants || []).map((agent) => [agent.name, agent]));
  return ROSTER.map((role) => {
    const live = hired.get(role.name) || {};
    const brief = (live.last || "").replace(/^Eye,\s*/i, "");
    return {
      ...role,
      brief,
      seen: live.seen || "",
      working: Boolean(brief),
    };
  });
}

function CrewCard({ agent }) {
  return (
    <article className="relative rounded-2xl border border-white/[0.08] bg-[#10141c] px-3 py-3">
      <div className="absolute -top-3 left-1/2 h-3 w-px -translate-x-1/2 bg-amber-300/40" />
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-medium text-slate-100">{agent.name}</div>
        <span className={`inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.14em] ${agent.working ? "text-emerald-300" : "text-slate-500"}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${agent.working ? "animate-pulse bg-emerald-300" : "bg-slate-600"}`} />
          {agent.working ? "Briefing" : "Waiting"}
        </span>
      </div>
      <div className="mt-1 text-[10px] uppercase tracking-[0.14em] text-amber-200/80">{agent.focus}</div>
      <p className="mt-2 text-xs leading-5 text-slate-400">{agent.task}</p>
      <p className="mt-2 line-clamp-3 text-sm leading-5 text-slate-200">
        {agent.brief || "Waiting for the next pass before briefing Eye."}
      </p>
    </article>
  );
}

const STATIONS = {
  Vet: { x: 12, y: 60, color: "#34d399" },
  "Scan watch": { x: 30, y: 78, color: "#38bdf8" },
  Scout: { x: 50, y: 84, color: "#c084fc" },
  Scribe: { x: 70, y: 78, color: "#fbbf24" },
  Risk: { x: 88, y: 60, color: "#fb7185" },
};

export function EyeFloor({ eye, phase, pick }) {
  const staff = staffOf(eye);
  const briefing = staff.filter((agent) => agent.working).length;
  const decision = eye?.growth?.[0]?.did || eye?.strategy || "Eye is waiting for the next pass.";
  return (
    <section className="overflow-hidden rounded-2xl border border-fuchsia-400/45 bg-[#080910] shadow-[inset_0_0_0_1px_rgba(232,121,249,0.18)]">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-fuchsia-400/25 px-4 py-2">
        <div className="text-[11px] uppercase tracking-[0.18em] text-fuchsia-200">Eye floor</div>
        <div className="text-[11px] text-slate-400">
          {phase || "waiting for a scan"} · last pick {pick || "none"} · {briefing} briefing
        </div>
      </div>
      <div className="relative h-[440px]">
        <div className="pointer-events-none absolute inset-x-6 bottom-8 top-28 origin-bottom rounded-xl border border-fuchsia-400/15 bg-[linear-gradient(rgba(232,121,249,0.07)_1px,transparent_1px),linear-gradient(90deg,rgba(232,121,249,0.07)_1px,transparent_1px)] bg-[size:32px_32px] [transform:perspective(680px)_rotateX(58deg)]" />
        <svg className="absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {staff.map((agent) => {
            const spot = STATIONS[agent.name];
            return (
              <line
                key={agent.name}
                x1={spot.x}
                y1={spot.y}
                x2="50"
                y2="30"
                stroke={spot.color}
                strokeWidth="0.35"
                strokeDasharray={agent.working ? "1.4 1.1" : "0.2 1.6"}
                className={agent.working ? "animate-eye-link" : ""}
                opacity={agent.working ? 0.95 : 0.35}
              />
            );
          })}
        </svg>
        <div className="absolute left-1/2 top-[18%] w-44 -translate-x-1/2 -translate-y-1/2">
          <div className="rounded-xl border border-amber-300/40 bg-amber-400/10 px-3 py-2 text-center shadow-[0_0_24px_rgba(251,191,36,0.18)]">
            <div className="mx-auto mb-1 grid h-8 w-8 place-items-center rounded-full bg-amber-300 text-xs font-semibold text-slate-950">E</div>
            <div className="text-[11px] uppercase tracking-[0.16em] text-amber-100">Eye · boss</div>
            <p className="mt-1 line-clamp-3 text-[11px] leading-4 text-slate-200">{decision}</p>
          </div>
        </div>
        {staff.map((agent) => {
          const spot = STATIONS[agent.name];
          return (
            <div
              key={agent.name}
              className="absolute w-32 -translate-x-1/2 -translate-y-1/2"
              style={{ left: `${spot.x}%`, top: `${spot.y}%` }}
            >
              <div className="rounded-xl border border-white/10 bg-[#10141c]/95 px-2.5 py-2">
                <div className="flex items-center gap-2">
                  <span
                    className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-[10px] font-semibold text-slate-950 ${agent.working ? "animate-pulse" : ""}`}
                    style={{ background: spot.color }}
                  >
                    {agent.name.slice(0, 1)}
                  </span>
                  <div className="min-w-0">
                    <div className="truncate text-[11px] font-medium text-slate-100">{agent.name}</div>
                    <div className="text-[10px] uppercase tracking-wide" style={{ color: spot.color }}>
                      {agent.working ? "Briefing" : "Waiting"}
                    </div>
                  </div>
                </div>
                <div className="mt-2 flex h-5 items-end gap-0.5">
                  {[0.35, 0.6, 0.45, 0.8, 0.55].map((h, i) => (
                    <span
                      key={i}
                      className="w-full rounded-sm"
                      style={{
                        height: `${h * 100}%`,
                        background: spot.color,
                        opacity: agent.working ? 0.85 : 0.3,
                      }}
                    />
                  ))}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

export function EyeCrew({ eye }) {
  const staff = staffOf(eye);
  const briefing = staff.filter((agent) => agent.working).length;
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="rounded-full border border-amber-300/40 bg-amber-400/15 px-2.5 py-1 font-medium text-amber-100">Eye · boss</span>
      {staff.map((agent) => (
        <span key={agent.name} className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-black/20 px-2.5 py-1 text-slate-300">
          <span className={`h-1.5 w-1.5 rounded-full ${agent.working ? "animate-pulse bg-emerald-300" : "bg-slate-600"}`} />
          {agent.name}
        </span>
      ))}
      <span className="text-slate-500">{briefing} of {staff.length} briefing Eye</span>
    </div>
  );
}

export default function EyeDesk({ eye, phase, onOptimize, optimizing }) {
  const staff = staffOf(eye);
  const briefing = staff.filter((agent) => agent.working).length;
  const decision = eye?.growth?.[0]?.did || eye?.strategy || "Eye is waiting for the next pass.";
  const last = eye?.last_optimize;
  return (
    <section className="overflow-hidden rounded-2xl border border-white/[0.07] bg-[#141820]/90">
      <div className="border-b border-white/[0.06] px-4 py-4 sm:px-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[11px] uppercase tracking-[0.16em] text-amber-200/80">Goal</div>
            <h2 className="mt-1 text-lg font-semibold text-slate-100">Find a profitable paper strategy</h2>
            <p className="mt-1 max-w-3xl text-sm text-slate-400">
              Scout researches the Lab and the book via cloud Anthropic. The others brief the scan, rugs, closes, and wallet risk. Eye is the only one who decides. Nobody spends.
            </p>
          </div>
          {onOptimize && (
            <button
              type="button"
              disabled={optimizing || eye?.anthropic === false}
              onClick={onOptimize}
              className="rounded-xl border border-violet-300/40 bg-violet-500/15 px-3 py-2 text-xs font-medium text-violet-100 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {optimizing ? "Researching…" : "Research & optimize"}
            </button>
          )}
        </div>
        {last?.at && (
          <p className="mt-2 text-xs text-slate-500">
            Last optimize {last.at}
            {last.move_count != null ? ` · ${last.move_count} rule move${last.move_count === 1 ? "" : "s"}` : ""}
            {last.model ? ` · ${last.model}` : ""}
          </p>
        )}
      </div>

      <div className="px-4 py-5 sm:px-5">
        <div className="mx-auto flex max-w-xl flex-col items-center">
          <div className="w-full rounded-2xl border border-amber-300/25 bg-amber-400/[0.08] px-4 py-3 text-center">
            <div className="text-[11px] uppercase tracking-[0.16em] text-amber-200">Eye · boss</div>
            <p className="mt-1 text-sm leading-6 text-slate-100">{decision}</p>
            <div className="mt-2 text-[11px] text-slate-500">
              {phase || "waiting for a scan"} · {briefing} of {staff.length} briefing
            </div>
          </div>
          <div className="h-6 w-px bg-amber-300/40" />
          <div className="h-px w-[78%] bg-amber-300/30" />
        </div>

        <div className="mt-0 grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          {staff.map((agent) => <CrewCard key={agent.name} agent={agent} />)}
        </div>

        {eye?.market && <p className="mt-4 text-xs leading-5 text-slate-500">{eye.market}</p>}
        {eye?.strategy && <p className="mt-2 text-sm text-slate-300">{eye.strategy}</p>}
      </div>
    </section>
  );
}
