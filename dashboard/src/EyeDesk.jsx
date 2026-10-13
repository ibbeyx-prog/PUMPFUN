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

export default function EyeDesk({ eye, phase }) {
  const staff = staffOf(eye);
  const briefing = staff.filter((agent) => agent.working).length;
  const decision = eye?.growth?.[0]?.did || eye?.strategy || "Eye is waiting for the next pass.";
  return (
    <section className="overflow-hidden rounded-2xl border border-white/[0.07] bg-[#141820]/90">
      <div className="border-b border-white/[0.06] px-4 py-4 sm:px-5">
        <div className="text-[11px] uppercase tracking-[0.16em] text-amber-200/80">Goal</div>
        <h2 className="mt-1 text-lg font-semibold text-slate-100">A paper book that pays</h2>
        <p className="mt-1 max-w-3xl text-sm text-slate-400">
          The assistants gather the scan, the rugs, and the book. Eye is the only one who decides. Nobody spends.
        </p>
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

        <div className="mt-0 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {staff.map((agent) => <CrewCard key={agent.name} agent={agent} />)}
        </div>

        {eye?.market && <p className="mt-4 text-xs leading-5 text-slate-500">{eye.market}</p>}
        {eye?.strategy && <p className="mt-2 text-sm text-slate-300">{eye.strategy}</p>}
      </div>
    </section>
  );
}
