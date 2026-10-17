import { Link, useParams } from "react-router";

import { getAutomation } from "../api";
import NetworkBadge from "../components/NetworkBadge";
import SpecPreview from "../components/SpecPreview";
import { CATEGORY_LABELS, fieldLabel, inputsOf, isOnline, settingsOf } from "../lib/fields";
import { useAsync } from "../lib/useAsync";
import type { AutomationSpec } from "../types/spec";
import NotFoundPage from "./NotFoundPage";

export default function AutomationPage() {
  const { id = "" } = useParams();
  const state = useAsync(() => getAutomation(id), [id]);

  if (state.status === "loading") return <p className="text-slate-500">Loading…</p>;
  if (state.status === "error") {
    return <p className="text-rose-700">Couldn't load this automation. Please refresh the page.</p>;
  }
  if (!state.data) return <NotFoundPage what="automation" />;
  return <AutomationDetails spec={state.data} />;
}

function AutomationDetails({ spec }: { spec: AutomationSpec }) {
  const settings = settingsOf(spec);
  const inputs = inputsOf(spec);

  return (
    <div>
      <Link to="/" className="text-sm font-medium text-indigo-700 hover:underline">
        ← All automations
      </Link>

      <div className="mt-4 grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:items-start">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {CATEGORY_LABELS[spec.category]}
            </span>
            <NetworkBadge spec={spec} />
          </div>
          <h1 className="mt-2 text-3xl font-bold tracking-tight">{spec.title}</h1>
          {spec.description && <p className="mt-3 text-slate-600">{spec.description}</p>}

          <div className="mt-6">
            <button
              type="button"
              disabled
              className="w-full cursor-not-allowed rounded-md bg-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-500 sm:w-auto"
            >
              Download for Windows
            </button>
            <p className="mt-2 text-sm text-slate-500">
              The download and step-by-step guide will be available here soon.
            </p>
          </div>

          {settings.length > 0 && (
            <FieldSummary title="Set up once" fields={settings.map(fieldLabel)} />
          )}
          {inputs.length > 0 && <FieldSummary title="Fill in each time" fields={inputs.map(fieldLabel)} />}

          <div className="mt-6 rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-600">
            <h2 className="font-semibold text-slate-900">Your data stays with you</h2>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {isOnline(spec) ? (
                <li>
                  Connects only to {(spec.network?.domains ?? []).join(", ")}, and nowhere else.
                </li>
              ) : (
                <li>Never connects to the internet.</li>
              )}
              <li>Your original files are never changed. Results are saved as new files.</li>
              <li>No tracking and no automatic updates.</li>
            </ul>
          </div>
        </div>

        <div>
          <h2 className="mb-3 text-sm font-semibold text-slate-700">What the app looks like</h2>
          <SpecPreview spec={spec} />
        </div>
      </div>
    </div>
  );
}

function FieldSummary({ title, fields }: { title: string; fields: string[] }) {
  return (
    <div className="mt-6">
      <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
      <p className="mt-1 text-sm text-slate-600">{fields.join(" · ")}</p>
    </div>
  );
}
