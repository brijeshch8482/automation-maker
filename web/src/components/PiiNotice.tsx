import { findPii, maskPii, PII_LABELS, type PiiKind } from "../lib/pii";

interface Props {
  id?: string;
  text: string;
  onMask: (masked: string) => void;
}

/** Warns when text looks like real personal or business data, with a one-click mask. */
export default function PiiNotice({ id, text, onMask }: Props) {
  const matches = findPii(text);
  if (matches.length === 0) return null;
  const kinds = [...new Set(matches.map((m) => m.kind))] as PiiKind[];

  return (
    <div
      id={id}
      role="alert"
      className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"
    >
      <p className="font-semibold">This looks like real personal or business data</p>
      <p className="mt-1">
        We found {listOf(kinds.map((k) => PII_LABELS[k]))}. Replace each one with a description of
        the field, for example "[phone number]".
      </p>
      <ul className="mt-2 flex flex-wrap gap-1.5">
        {matches.map((m) => (
          <li
            key={`${m.start}-${m.end}`}
            className="rounded bg-amber-100 px-1.5 py-0.5 font-mono text-xs"
          >
            {m.text}
          </li>
        ))}
      </ul>
      <button
        type="button"
        className="mt-3 rounded-md bg-amber-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-amber-500"
        onClick={() => onMask(maskPii(text, matches))}
      >
        Mask all
      </button>
    </div>
  );
}

export function hasPii(text: string): boolean {
  return findPii(text).length > 0;
}

function listOf(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;
}
