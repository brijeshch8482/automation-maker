import type { ComponentType, ReactNode, SVGProps } from "react";
import { Link, useParams } from "react-router";

import { getAutomation } from "../api";
import { CategoryIcon } from "../components/AutomationCard";
import DownloadCard from "../components/DownloadCard";
import { EyeOff, Shield, Undo, WifiOff } from "../components/icons";
import NetworkBadge from "../components/NetworkBadge";
import SpecPreview from "../components/SpecPreview";
import { usePageMeta } from "../components/ui";
import {
  CATEGORY_LABELS,
  changesFiles,
  fieldLabel,
  inputsOf,
  isOnline,
  settingsOf,
} from "../lib/fields";
import { useAsync } from "../lib/useAsync";
import type { AutomationSpec } from "../types/spec";
import NotFoundPage from "./NotFoundPage";

export default function AutomationPage() {
  const { id = "" } = useParams();
  const state = useAsync(() => getAutomation(id), [id]);
  const spec = state.status === "ready" ? state.data : null;
  usePageMeta(spec ? spec.title : state.status === "loading" ? null : "Not found", spec?.description);

  if (state.status === "loading") return <p className="text-slate-500">Loading…</p>;
  if (state.status === "error") {
    return <p className="text-rose-700">Couldn't load this automation. Please refresh the page.</p>;
  }
  if (!spec) return <NotFoundPage what="automation" />;
  return <AutomationDetails spec={spec} />;
}

function AutomationDetails({ spec }: { spec: AutomationSpec }) {
  const settings = settingsOf(spec);
  const inputs = inputsOf(spec);

  return (
    <div>
      <nav aria-label="Breadcrumb" className="text-sm text-slate-500">
        <Link to="/automations" className="font-medium text-brand-700 hover:underline">
          Automations
        </Link>
        <span className="mx-2" aria-hidden>
          /
        </span>
        <span aria-current="page">{spec.title}</span>
      </nav>

      <div className="mt-6 grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:items-start">
        <div>
          <div className="flex items-center gap-4">
            <CategoryIcon category={spec.category} className="h-14 w-14" />
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                {CATEGORY_LABELS[spec.category]}
              </p>
              <h1 className="text-3xl font-bold tracking-tight text-slate-900">{spec.title}</h1>
            </div>
          </div>
          <div className="mt-4">
            <NetworkBadge spec={spec} />
          </div>
          {spec.description && <p className="mt-5 text-lg leading-8 text-slate-600">{spec.description}</p>}

          <div className="mt-8">
            <DownloadCard automationId={spec.id} />
          </div>

          {settings.length > 0 && <FieldSummary title="Set up once" fields={settings.map(fieldLabel)} />}
          {inputs.length > 0 && <FieldSummary title="Fill in each time" fields={inputs.map(fieldLabel)} />}

          <div className="mt-8">
            <h2 className="text-sm font-semibold text-slate-900">Your data stays with you</h2>
            <ul className="mt-3 space-y-2.5 text-sm text-slate-600">
              <DataPromise icon={isOnline(spec) ? Shield : WifiOff}>
                {isOnline(spec)
                  ? `Connects only to ${(spec.network?.domains ?? []).join(", ")}, and nowhere else.`
                  : "Never connects to the internet."}
              </DataPromise>
              <DataPromise icon={Undo}>
                {changesFiles(spec)
                  ? "Files are renamed only after you check a preview of the new names. Undo puts the old names back, and nothing is ever deleted."
                  : "Your original files are never changed. Results are saved as new files."}
              </DataPromise>
              <DataPromise icon={EyeOff}>No tracking and no automatic updates.</DataPromise>
            </ul>
          </div>
        </div>

        <div className="lg:sticky lg:top-24">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">What the app looks like</h2>
          <SpecPreview spec={spec} />
          <p className="mt-3 text-center text-xs text-slate-500">
            Filled in with example data. Try the form: it works like the real app.
          </p>
        </div>
      </div>
    </div>
  );
}

function FieldSummary({ title, fields }: { title: string; fields: string[] }) {
  return (
    <div className="mt-8">
      <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
      <ul className="mt-3 flex flex-wrap gap-2">
        {fields.map((field) => (
          <li key={field} className="rounded-full border border-slate-200 bg-white px-3 py-1 text-sm text-slate-700">
            {field}
          </li>
        ))}
      </ul>
    </div>
  );
}

function DataPromise({ icon: Icon, children }: { icon: ComponentType<SVGProps<SVGSVGElement>>; children: ReactNode }) {
  return (
    <li className="flex gap-2.5">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
      <span>{children}</span>
    </li>
  );
}
