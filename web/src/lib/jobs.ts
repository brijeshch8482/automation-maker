import type { JobAttempt, JobState } from "../api";

/** States where the server is working and the page should keep checking. */
export const WAITING_STATES: ReadonlySet<JobState> = new Set([
  "draft",
  "spec_requested",
  "queued",
  "generating",
  "building",
  "repairing",
]);

export const STATE_LABELS: Record<JobState, string> = {
  draft: "Starting",
  spec_requested: "Designing",
  spec_ready: "Ready to review",
  queued: "Waiting to build",
  generating: "Generating",
  building: "Building",
  repairing: "Fixing a problem",
  ready: "Ready",
  failed: "Failed",
  expired: "Expired",
};

export const STATE_TONES: Record<JobState, string> = {
  draft: "bg-slate-100 text-slate-700",
  spec_requested: "bg-indigo-50 text-indigo-800",
  spec_ready: "bg-amber-50 text-amber-800",
  queued: "bg-indigo-50 text-indigo-800",
  generating: "bg-indigo-50 text-indigo-800",
  building: "bg-indigo-50 text-indigo-800",
  repairing: "bg-indigo-50 text-indigo-800",
  ready: "bg-emerald-50 text-emerald-800",
  failed: "bg-rose-50 text-rose-800",
  expired: "bg-slate-100 text-slate-600",
};

export const ATTEMPT_LABELS: Record<JobAttempt["mode"], string> = {
  spec: "Design",
  build: "Generate code",
  repair: "Repair",
};

export const ATTEMPT_STATUS_LABELS: Record<string, string> = {
  firing: "Starting",
  open: "Running",
  unknown: "Running",
  rate_limited: "Busy, retried",
  ok: "Done",
  failed: "Failed",
  timed_out: "Timed out",
};

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
