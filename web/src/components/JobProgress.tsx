import type { JobState } from "../api";

const STEPS = ["Describe", "Design", "Review", "Generate", "Build", "Ready"] as const;

const STEP_OF_STATE: Record<JobState, number> = {
  draft: 0,
  spec_requested: 1,
  spec_ready: 2,
  queued: 3,
  generating: 3,
  building: 4,
  repairing: 4,
  ready: 5,
  failed: -1,
  expired: -1,
};

/** Where the job is in the flow. Failed and expired jobs show no step as current. */
export default function JobProgress({ state }: { state: JobState }) {
  const current = STEP_OF_STATE[state];
  return (
    <ol aria-label="Progress" className="flex flex-wrap items-center gap-x-2 gap-y-2 text-xs sm:text-sm">
      {STEPS.map((step, i) => {
        const done = current >= 0 && (i < current || state === "ready");
        const active = i === current && state !== "ready";
        return (
          <li key={step} className="flex items-center gap-2" aria-current={active ? "step" : undefined}>
            <span
              className={`flex h-6 items-center gap-1.5 rounded-full px-2.5 font-medium ${
                done
                  ? "bg-emerald-50 text-emerald-800"
                  : active
                    ? "bg-indigo-600 text-white"
                    : "bg-slate-100 text-slate-500"
              }`}
            >
              {done && <span aria-hidden>✓</span>}
              {step}
            </span>
            {i < STEPS.length - 1 && <span aria-hidden className="text-slate-300">›</span>}
          </li>
        );
      })}
    </ol>
  );
}
