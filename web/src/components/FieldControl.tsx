import type { ReactNode } from "react";

import { emptyRow, fieldLabel, type TableRow } from "../lib/fields";
import type { ColumnField, SpecField, TableField } from "../types/spec";

const CURRENCY_SYMBOLS: Record<string, string> = { INR: "₹", USD: "$", EUR: "€", GBP: "£" };

const inputClass =
  "block w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-900 " +
  "placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20";

interface ControlProps<F> {
  id: string;
  field: F;
  value: unknown;
  onChange: (value: unknown) => void;
}

const asText = (value: unknown) => (value == null ? "" : String(value));

/** The editable control for one field, as the EXE shows it. */
export function FieldControl({ id, field, value, onChange }: ControlProps<SpecField | ColumnField>) {
  const label = fieldLabel(field);
  switch (field.type) {
    case "text":
      return field.multiline ? (
        <textarea
          id={id}
          rows={3}
          className={inputClass}
          value={asText(value)}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <input id={id} className={inputClass} value={asText(value)} onChange={(e) => onChange(e.target.value)} />
      );
    case "number":
      return (
        <input
          id={id}
          type="number"
          inputMode="decimal"
          className={inputClass}
          min={field.min ?? undefined}
          max={field.max ?? undefined}
          value={asText(value)}
          onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
        />
      );
    case "money": {
      const currency = field.currency ?? "INR";
      return (
        <div className="relative">
          <span className="pointer-events-none absolute inset-y-0 left-2.5 flex items-center text-sm text-slate-500">
            {CURRENCY_SYMBOLS[currency] ?? currency}
          </span>
          <input
            id={id}
            type="number"
            inputMode="decimal"
            step="0.01"
            className={`${inputClass} pl-7`}
            value={asText(value)}
            onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
          />
        </div>
      );
    }
    case "phone":
      return (
        <input id={id} type="tel" className={inputClass} value={asText(value)} onChange={(e) => onChange(e.target.value)} />
      );
    case "email":
      return (
        <input id={id} type="email" className={inputClass} value={asText(value)} onChange={(e) => onChange(e.target.value)} />
      );
    case "date":
      return (
        <input id={id} type="date" className={inputClass} value={asText(value)} onChange={(e) => onChange(e.target.value)} />
      );
    case "select":
      return (
        <select id={id} className={inputClass} value={asText(value)} onChange={(e) => onChange(e.target.value)}>
          {!value && <option value="">Choose…</option>}
          {field.options.map((option) => (
            <option key={option}>{option}</option>
          ))}
        </select>
      );
    case "checkbox":
      return (
        <input
          id={id}
          type="checkbox"
          className="h-4 w-4 rounded border-slate-300 text-indigo-600"
          checked={value === true}
          onChange={(e) => onChange(e.target.checked)}
        />
      );
    case "file":
      return <PickerRow id={id} value={asText(value)} empty="No file selected" action="Browse…" />;
    case "image_file":
      return <PickerRow id={id} value={asText(value)} empty="No image selected" action="Browse…" />;
    case "folder":
      return <PickerRow id={id} value={asText(value)} empty="No folder selected" action="Choose folder…" />;
    case "files": {
      const names = Array.isArray(value) ? value.map(String) : [];
      return (
        <PickerRow
          id={id}
          value={names.length ? `${names.length} file${names.length > 1 ? "s" : ""}: ${names.join(", ")}` : ""}
          empty="No files selected"
          action="Add files…"
        />
      );
    }
    case "table":
      return <TableControl id={id} field={field} value={value} onChange={onChange} label={label} />;
  }
}

/** File and folder pickers: the web preview can't open a dialog, so it shows the EXE's layout. */
function PickerRow({ id, value, empty, action }: { id: string; value: string; empty: string; action: string }) {
  return (
    <div className="flex gap-2">
      <input
        id={id}
        readOnly
        className={`${inputClass} min-w-0 flex-1 bg-slate-50 ${value ? "" : "italic text-slate-400"}`}
        value={value || empty}
      />
      <button
        type="button"
        className="shrink-0 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
        title="Opens the Windows file dialog in the app"
      >
        {action}
      </button>
    </div>
  );
}

function TableControl({ id, field, value, onChange, label }: ControlProps<TableField> & { label: string }) {
  const rows: TableRow[] = Array.isArray(value) ? (value as TableRow[]) : [];
  const setRows = (next: TableRow[]) => onChange(next);
  const setCell = (rowIndex: number, key: string, cell: unknown) =>
    setRows(rows.map((row, i) => (i === rowIndex ? { ...row, [key]: cell } : row)));

  return (
    <div id={id} role="group" aria-label={label} className="rounded-md border border-slate-300">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[20rem] text-sm">
          <thead className="bg-slate-50 text-left text-xs font-semibold text-slate-600">
            <tr>
              {field.columns.map((column) => (
                <th key={column.key} scope="col" className="px-2 py-1.5 font-semibold">
                  {fieldLabel(column)}
                </th>
              ))}
              <th className="w-8" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={field.columns.length + 1} className="px-2 py-3 text-center text-slate-400 italic">
                  No rows yet
                </td>
              </tr>
            )}
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex} className="border-t border-slate-200">
                {field.columns.map((column) => (
                  <Cell key={column.key}>
                    <FieldControl
                      id={`${id}-${rowIndex}-${column.key}`}
                      field={column}
                      value={row[column.key]}
                      onChange={(cell) => setCell(rowIndex, column.key, cell)}
                    />
                  </Cell>
                ))}
                <td className="px-1 text-center">
                  <button
                    type="button"
                    aria-label={`Remove row ${rowIndex + 1}`}
                    className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                    onClick={() => setRows(rows.filter((_, i) => i !== rowIndex))}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="border-t border-slate-200 px-2 py-1.5">
        <button
          type="button"
          className="text-sm font-medium text-indigo-700 hover:underline"
          onClick={() => setRows([...rows, emptyRow(field.columns)])}
        >
          + Add row
        </button>
      </div>
    </div>
  );
}

function Cell({ children }: { children: ReactNode }) {
  return <td className="px-1.5 py-1 align-middle">{children}</td>;
}
