import { isOnline } from "../lib/fields";
import type { AutomationSpec } from "../types/spec";

export default function NetworkBadge({ spec }: { spec: AutomationSpec }) {
  if (isOnline(spec)) {
    const domains = spec.network?.domains ?? [];
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-800 ring-1 ring-amber-200"
        title={`Connects only to: ${domains.join(", ")}`}
      >
        <span aria-hidden>🌐</span> Uses internet
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-800 ring-1 ring-emerald-200"
      title="Never connects to the internet"
    >
      <span aria-hidden>🔒</span> Works offline
    </span>
  );
}
