import { useMemo, useState } from "react";

import { listAutomations, type AutomationSummary } from "../api";
import AutomationCard from "../components/AutomationCard";
import { ArrowRight, Search } from "../components/icons";
import { ButtonLink, Eyebrow, usePageMeta } from "../components/ui";
import { CATEGORY_LABELS } from "../lib/fields";
import { useAsync } from "../lib/useAsync";

type Category = AutomationSummary["category"];

export default function CatalogPage() {
  usePageMeta(
    "Automations",
    "Ready-made Windows automations: make PDFs from photos, merge PDFs, rename files, create invoices. Offline, no installation.",
  );
  const state = useAsync(listAutomations, []);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<Category | "all">("all");

  const all = state.status === "ready" ? state.data : [];
  const categories = useMemo(
    () => [...new Set(all.map((spec) => spec.category))].sort((a, b) => CATEGORY_LABELS[a].localeCompare(CATEGORY_LABELS[b])),
    [all],
  );
  const shown = all.filter((spec) => {
    if (category !== "all" && spec.category !== category) return false;
    const text = `${spec.title} ${spec.description ?? ""} ${CATEGORY_LABELS[spec.category]}`.toLowerCase();
    return query
      .toLowerCase()
      .split(/\s+/)
      .every((word) => text.includes(word));
  });

  return (
    <div>
      <div className="max-w-2xl">
        <Eyebrow>Catalog</Eyebrow>
        <h1 className="mt-3 text-4xl font-bold tracking-tight text-slate-900">Ready-made automations</h1>
        <p className="mt-4 text-lg leading-8 text-slate-600">
          Complete Windows apps for everyday tasks. Each one runs offline on your PC and comes with
          a step-by-step guide.
        </p>
      </div>

      <div className="mt-10 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="relative w-full lg:max-w-sm">
          <Search className="pointer-events-none absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search automations"
            aria-label="Search automations"
            className="block w-full rounded-xl border border-slate-300 bg-white py-2.5 pl-11 pr-4 text-sm shadow-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
          />
        </div>
        <div role="group" aria-label="Category" className="flex flex-wrap gap-2">
          {(["all", ...categories] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={category === value}
              onClick={() => setCategory(value)}
              className={`rounded-full px-4 py-1.5 text-sm font-medium transition-colors ${
                category === value
                  ? "bg-slate-900 text-white"
                  : "border border-slate-300 bg-white text-slate-700 hover:border-slate-400"
              }`}
            >
              {value === "all" ? "All" : CATEGORY_LABELS[value]}
            </button>
          ))}
        </div>
      </div>

      {state.status === "ready" && (
        <p className="mt-6 text-sm text-slate-500" aria-live="polite">
          {shown.length === all.length
            ? `${all.length} automations`
            : `${shown.length} of ${all.length} automations`}
        </p>
      )}

      {shown.length > 0 ? (
        <ul className="mt-4 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {shown.map((spec) => (
            <li key={spec.id}>
              <AutomationCard spec={spec} />
            </li>
          ))}
        </ul>
      ) : (
        state.status === "ready" && (
          <div className="mt-4 rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-6 py-14 text-center">
            <p className="font-semibold text-slate-900">
              {query ? `No automation matches “${query}”` : "No automations here yet"}
            </p>
            <p className="mt-2 text-sm text-slate-600">Describe your task and we'll build an app for it.</p>
            <ButtonLink to="/custom" className="mt-6">
              Request a custom app <ArrowRight className="h-4 w-4" />
            </ButtonLink>
          </div>
        )
      )}

      <div className="mt-16 flex flex-col items-start justify-between gap-6 rounded-2xl border border-slate-200 bg-slate-50 p-8 sm:flex-row sm:items-center">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Need something different?</h2>
          <p className="mt-1 text-sm text-slate-600">
            Describe your task in plain words and we'll design, build and test an app for it.
          </p>
        </div>
        <ButtonLink to="/custom" variant="secondary" className="shrink-0">
          Request a custom app
        </ButtonLink>
      </div>
    </div>
  );
}
