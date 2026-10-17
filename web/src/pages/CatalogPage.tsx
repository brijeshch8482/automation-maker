import { Link } from "react-router";

import { listAutomations } from "../api";
import NetworkBadge from "../components/NetworkBadge";
import { CATEGORY_LABELS } from "../lib/fields";
import { useAsync } from "../lib/useAsync";

export default function CatalogPage() {
  const state = useAsync(listAutomations, []);

  return (
    <div>
      <section className="max-w-2xl">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
          Automations that run on your own PC
        </h1>
        <p className="mt-3 text-lg text-slate-600">
          Pick a ready-made tool, or describe your own task and we'll build a Windows app for it.
          It works offline, and your files never leave your computer.
        </p>
        <Link
          to="/custom"
          className="mt-5 inline-block rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500"
        >
          Describe a custom automation
        </Link>
      </section>

      <section className="mt-10" aria-labelledby="catalog-heading">
        <h2 id="catalog-heading" className="text-lg font-semibold">
          Ready-made
        </h2>
        {state.status === "loading" && <p className="mt-4 text-slate-500">Loading…</p>}
        {state.status === "error" && (
          <p className="mt-4 text-rose-700">Couldn't load the catalog. Please refresh the page.</p>
        )}
        {state.status === "ready" && state.data.length === 0 && (
          <p className="mt-4 text-slate-500">No automations yet.</p>
        )}
        {state.status === "ready" && state.data.length > 0 && (
          <ul className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {state.data.map((spec) => (
              <li key={spec.id}>
                <Link
                  to={`/automations/${spec.id}`}
                  className="flex h-full flex-col rounded-lg border border-slate-200 bg-white p-5 shadow-sm transition hover:border-indigo-300 hover:shadow-md"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
                      {CATEGORY_LABELS[spec.category]}
                    </span>
                    <NetworkBadge spec={spec} />
                  </div>
                  <h3 className="mt-3 text-base font-semibold text-slate-900">{spec.title}</h3>
                  {spec.description && (
                    <p className="mt-1.5 text-sm text-slate-600">{spec.description}</p>
                  )}
                  <span className="mt-auto pt-4 text-sm font-medium text-indigo-700">
                    See how it works →
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
