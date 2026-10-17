import { useState } from "react";

import { fieldLabel } from "../lib/fields";
import {
  ADDABLE_TYPES,
  addField,
  moveField,
  removeField,
  setTitle,
  TYPE_LABELS,
  updateField,
  type AddableType,
  type Section,
} from "../lib/specEdit";
import type { AutomationSpec } from "../types/spec";
import { Button } from "./ui";

interface Props {
  spec: AutomationSpec;
  onChange: (spec: AutomationSpec) => void;
}

const inputClass =
  "block w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20";

/** Edit the parts of a spec a user cares about: title and fields. Steps stay as designed. */
export default function SpecEditor({ spec, onChange }: Props) {
  return (
    <div className="space-y-5">
      <div>
        <label htmlFor="spec-title" className="mb-1 block text-sm font-medium text-slate-800">
          App name
        </label>
        <input
          id="spec-title"
          className={inputClass}
          maxLength={80}
          value={spec.title}
          onChange={(e) => onChange(setTitle(spec, e.target.value))}
        />
      </div>
      <FieldSection
        title="Set up once"
        hint="Saved on the PC, e.g. your business name."
        section="settings"
        spec={spec}
        onChange={onChange}
      />
      <FieldSection
        title="Fill in each time"
        hint="What you type or pick on every run."
        section="inputs"
        spec={spec}
        onChange={onChange}
      />
    </div>
  );
}

function FieldSection({
  title,
  hint,
  section,
  spec,
  onChange,
}: Props & { title: string; hint: string; section: Section }) {
  const fields = spec[section] ?? [];
  return (
    <fieldset>
      <legend className="text-sm font-semibold text-slate-900">{title}</legend>
      <p className="text-xs text-slate-500">{hint}</p>
      <ul className="mt-2 divide-y divide-slate-200 rounded-md border border-slate-200">
        {fields.length === 0 && <li className="px-3 py-2 text-sm italic text-slate-400">No fields</li>}
        {fields.map((field, i) => {
          const name = fieldLabel(field);
          return (
            <li key={field.key} className="flex flex-wrap items-center gap-2 px-2.5 py-2 sm:flex-nowrap">
              <input
                aria-label={`Label for ${name}`}
                className={`${inputClass} min-w-0 basis-full sm:flex-1 sm:basis-0`}
                maxLength={120}
                value={field.label ?? ""}
                placeholder={name}
                onChange={(e) => onChange(updateField(spec, section, i, { label: e.target.value }))}
              />
              <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                {TYPE_LABELS[field.type]}
              </span>
              <label className="flex shrink-0 items-center gap-1 text-xs text-slate-700">
                <input
                  type="checkbox"
                  checked={field.required === true}
                  onChange={(e) =>
                    onChange(updateField(spec, section, i, { required: e.target.checked }))
                  }
                />
                Required
              </label>
              <span className="ml-auto flex shrink-0 items-center">
                <IconButton
                  label={`Move ${name} up`}
                  disabled={i === 0}
                  onClick={() => onChange(moveField(spec, section, i, -1))}
                >
                  ↑
                </IconButton>
                <IconButton
                  label={`Move ${name} down`}
                  disabled={i === fields.length - 1}
                  onClick={() => onChange(moveField(spec, section, i, 1))}
                >
                  ↓
                </IconButton>
                <IconButton label={`Remove ${name}`} onClick={() => onChange(removeField(spec, section, i))}>
                  ✕
                </IconButton>
              </span>
            </li>
          );
        })}
      </ul>
      <AddField section={section} spec={spec} onChange={onChange} />
    </fieldset>
  );
}

function AddField({ section, spec, onChange }: Props & { section: Section }) {
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [type, setType] = useState<AddableType>("text");
  const [options, setOptions] = useState("");

  if (!open) {
    return (
      <button
        type="button"
        className="mt-2 text-sm font-medium text-indigo-700 hover:underline"
        onClick={() => setOpen(true)}
      >
        + Add a field
      </button>
    );
  }

  const add = () => {
    const optionList = options.split(",").map((o) => o.trim()).filter(Boolean);
    onChange(addField(spec, section, { label, type, options: optionList }));
    setLabel("");
    setOptions("");
    setOpen(false);
  };
  const prefix = `add-${section}`;

  return (
    <div className="mt-2 grid gap-2 rounded-md bg-slate-50 p-2.5 sm:grid-cols-[1fr_auto]">
      <div>
        <label htmlFor={`${prefix}-label`} className="mb-1 block text-xs font-medium text-slate-700">
          New field name
        </label>
        <input
          id={`${prefix}-label`}
          className={inputClass}
          maxLength={120}
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
      </div>
      <div>
        <label htmlFor={`${prefix}-type`} className="mb-1 block text-xs font-medium text-slate-700">
          Type
        </label>
        <select
          id={`${prefix}-type`}
          className={inputClass}
          value={type}
          onChange={(e) => setType(e.target.value as AddableType)}
        >
          {ADDABLE_TYPES.map((t) => (
            <option key={t} value={t}>
              {TYPE_LABELS[t]}
            </option>
          ))}
        </select>
      </div>
      {type === "select" && (
        <div className="sm:col-span-2">
          <label htmlFor={`${prefix}-options`} className="mb-1 block text-xs font-medium text-slate-700">
            Choices, separated by commas
          </label>
          <input
            id={`${prefix}-options`}
            className={inputClass}
            value={options}
            onChange={(e) => setOptions(e.target.value)}
          />
        </div>
      )}
      <div className="flex gap-2 sm:col-span-2">
        <Button onClick={add} disabled={!label.trim()}>
          Add
        </Button>
        <Button variant="secondary" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function IconButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled?: boolean;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="rounded p-1.5 text-sm text-slate-500 hover:bg-slate-100 hover:text-slate-800 disabled:opacity-30"
    >
      {children}
    </button>
  );
}
