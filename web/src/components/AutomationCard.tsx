import type { ComponentType, SVGProps } from "react";
import { Link } from "react-router";

import type { AutomationSummary } from "../api";
import { CATEGORY_LABELS } from "../lib/fields";
import type { AutomationSpec } from "../types/spec";
import { ArrowRight, Box, Convert, FileText, Folder, ImageIcon, Pdf, Table } from "./icons";
import NetworkBadge from "./NetworkBadge";

const CATEGORY_ICONS: Record<AutomationSpec["category"], ComponentType<SVGProps<SVGSVGElement>>> = {
  documents: FileText,
  pdf: Pdf,
  images: ImageIcon,
  excel: Table,
  files: Folder,
  convert: Convert,
  other: Box,
};

export function CategoryIcon({ category, className = "h-11 w-11" }: { category: AutomationSpec["category"]; className?: string }) {
  const Icon = CATEGORY_ICONS[category] ?? Box;
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600 ring-1 ring-brand-100 ${className}`}
    >
      <Icon className="h-[55%] w-[55%]" />
    </span>
  );
}

export default function AutomationCard({ spec }: { spec: AutomationSummary }) {
  return (
    <Link
      to={`/automations/${spec.id}`}
      className="group flex h-full flex-col rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-lg hover:shadow-brand-900/5"
    >
      <div className="flex items-start justify-between gap-3">
        <CategoryIcon category={spec.category} />
        <NetworkBadge spec={spec} />
      </div>
      <p className="mt-5 text-xs font-semibold uppercase tracking-wider text-slate-500">
        {CATEGORY_LABELS[spec.category]}
      </p>
      <h3 className="mt-1 text-lg font-semibold text-slate-900">{spec.title}</h3>
      {spec.description && <p className="mt-2 text-sm leading-6 text-slate-600">{spec.description}</p>}
      <span className="mt-auto flex items-center gap-1.5 pt-5 text-sm font-semibold text-brand-700">
        See how it works
        <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
      </span>
    </Link>
  );
}
