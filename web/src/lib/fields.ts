import type { AutomationSpec, ColumnField, SpecField } from "../types/spec";

export type FieldValues = Record<string, unknown>;
export type TableRow = Record<string, unknown>;

/** "customer_name" -> "Customer name" */
export function humanize(key: string): string {
  const words = key.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function fieldLabel(field: SpecField | ColumnField): string {
  return field.label || humanize(field.key);
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Starting value for a field: sample data first, then the field's default, then empty. */
export function initialValue(field: SpecField | ColumnField, sample: FieldValues): unknown {
  if (field.key in sample) return sample[field.key];
  switch (field.type) {
    case "checkbox":
      return field.default ?? false;
    case "table":
      return [];
    case "files":
      return [];
    case "date":
      return field.default === "today" ? todayIso() : "";
    case "file":
    case "folder":
    case "image_file":
      return "";
    default:
      return field.default ?? "";
  }
}

export function initialValues(fields: SpecField[], sample: FieldValues): FieldValues {
  return Object.fromEntries(fields.map((f) => [f.key, initialValue(f, sample)]));
}

export function emptyRow(columns: ColumnField[]): TableRow {
  return Object.fromEntries(columns.map((c) => [c.key, initialValue(c, {})]));
}

export function settingsOf(spec: AutomationSpec): SpecField[] {
  return spec.settings ?? [];
}

export function inputsOf(spec: AutomationSpec): SpecField[] {
  return spec.inputs ?? [];
}

export function isOnline(spec: Pick<AutomationSpec, "network">): boolean {
  return spec.network?.required === true;
}

export const CATEGORY_LABELS: Record<AutomationSpec["category"], string> = {
  documents: "Documents",
  pdf: "PDF",
  images: "Images",
  excel: "Excel",
  files: "Files & folders",
  convert: "Convert",
  other: "Other",
};
