import { useMemo, useState } from "react";

import { findPii, maskPii, PII_LABELS, type PiiKind } from "../lib/pii";

const EXAMPLE =
  "Every month I get a folder of vendor bills as PDFs. I want one Excel sheet listing vendor " +
  "name, bill number, date and amount from each bill.";

export default function CustomPage() {
  const [description, setDescription] = useState("");
  const matches = useMemo(() => findPii(description), [description]);
  const kinds = [...new Set(matches.map((m) => m.kind))] as PiiKind[];

  return (
    <div className="max-w-2xl">
      <h1 className="text-3xl font-bold tracking-tight">Describe your automation</h1>
      <p className="mt-3 text-slate-600">
        Tell us what you do by hand today. We only need the <em>format</em> of the task: what
        goes in, what should come out. Don't include real names, numbers or files. You'll enter
        your real data inside the app, on your own PC.
      </p>

      <form className="mt-6" onSubmit={(e) => e.preventDefault()}>
        <label htmlFor="description" className="block text-sm font-medium text-slate-800">
          What should it do?
        </label>
        <textarea
          id="description"
          rows={7}
          maxLength={4000}
          className="mt-1.5 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          placeholder={EXAMPLE}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          aria-describedby={matches.length ? "pii-warning" : undefined}
        />

        {matches.length > 0 && (
          <div
            id="pii-warning"
            role="alert"
            className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"
          >
            <p className="font-semibold">This looks like real personal or business data</p>
            <p className="mt-1">
              We found {listOf(kinds.map((k) => PII_LABELS[k]))}. Replace each one with a description
              of the field, for example "[phone number]".
            </p>
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {matches.map((m) => (
                <li key={`${m.start}-${m.end}`} className="rounded bg-amber-100 px-1.5 py-0.5 font-mono text-xs">
                  {m.text}
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="mt-3 rounded-md bg-amber-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-amber-500"
              onClick={() => setDescription(maskPii(description, matches))}
            >
              Mask all
            </button>
          </div>
        )}

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled
            className="cursor-not-allowed rounded-md bg-slate-200 px-4 py-2 text-sm font-semibold text-slate-500"
          >
            Design my automation
          </button>
          <p className="text-sm text-slate-500">Custom builds open soon.</p>
        </div>
      </form>
    </div>
  );
}

function listOf(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;
}
