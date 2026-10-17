import type { JobState } from "../api";
import { STATE_LABELS, STATE_TONES } from "../lib/jobs";

export default function StateBadge({ state }: { state: JobState }) {
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${STATE_TONES[state]}`}>
      {STATE_LABELS[state]}
    </span>
  );
}
