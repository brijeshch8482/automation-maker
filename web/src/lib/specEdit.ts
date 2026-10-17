// Pure edits to an AutomationSpec, used by the spec editor on the job page. The server
// validates every saved spec, so these only keep keys unique and sample_data in step.

import type { AutomationSpec, SpecField } from "../types/spec";

export type Section = "settings" | "inputs";

/** Field types a user can add from the editor (no extra required config beyond options). */
export const ADDABLE_TYPES = [
  "text",
  "number",
  "money",
  "phone",
  "email",
  "date",
  "file",
  "files",
  "folder",
  "image_file",
  "select",
  "checkbox",
] as const;
export type AddableType = (typeof ADDABLE_TYPES)[number];

export const TYPE_LABELS: Record<SpecField["type"], string> = {
  text: "Text",
  number: "Number",
  money: "Money",
  phone: "Phone",
  email: "Email",
  date: "Date",
  file: "File",
  files: "Files",
  folder: "Folder",
  image_file: "Image",
  select: "Choice",
  checkbox: "Checkbox",
  table: "Table",
};

const fieldsOf = (spec: AutomationSpec, section: Section): SpecField[] => spec[section] ?? [];

function withFields(spec: AutomationSpec, section: Section, fields: SpecField[]): AutomationSpec {
  return { ...spec, [section]: fields };
}

export function setTitle(spec: AutomationSpec, title: string): AutomationSpec {
  return { ...spec, title };
}

export function updateField(
  spec: AutomationSpec,
  section: Section,
  index: number,
  patch: { label?: string; required?: boolean },
): AutomationSpec {
  const fields = fieldsOf(spec, section).map((f, i) => (i === index ? { ...f, ...patch } : f));
  return withFields(spec, section, fields);
}

export function moveField(
  spec: AutomationSpec,
  section: Section,
  index: number,
  delta: -1 | 1,
): AutomationSpec {
  const fields = [...fieldsOf(spec, section)];
  const target = index + delta;
  if (target < 0 || target >= fields.length) return spec;
  [fields[index], fields[target]] = [fields[target]!, fields[index]!];
  return withFields(spec, section, fields);
}

export function removeField(spec: AutomationSpec, section: Section, index: number): AutomationSpec {
  const fields = fieldsOf(spec, section);
  const removed = fields[index];
  if (!removed) return spec;
  const sample = { ...(spec.sample_data ?? {}) };
  delete sample[removed.key];
  return { ...withFields(spec, section, fields.filter((_, i) => i !== index)), sample_data: sample };
}

/** "Customer GST no." -> "customer_gst_no" (a valid spec key). */
export function slugify(label: string): string {
  const slug = label
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 50);
  return /^[a-z]/.test(slug) ? slug : `field_${slug}`.replace(/_+$/, "");
}

export function uniqueKey(spec: AutomationSpec, label: string): string {
  const taken = new Set([...fieldsOf(spec, "settings"), ...fieldsOf(spec, "inputs")].map((f) => f.key));
  const base = slugify(label);
  let key = base;
  for (let n = 2; taken.has(key); n++) key = `${base}_${n}`;
  return key;
}

export function addField(
  spec: AutomationSpec,
  section: Section,
  { label, type, options = [] }: { label: string; type: AddableType; options?: string[] },
): AutomationSpec {
  const key = uniqueKey(spec, label);
  const base = { key, label: label.trim() };
  const field: SpecField =
    type === "select"
      ? { ...base, type, options: options.length ? (options as [string, ...string[]]) : ["Option 1"] }
      : ({ ...base, type } as SpecField);
  return withFields(spec, section, [...fieldsOf(spec, section), field]);
}
