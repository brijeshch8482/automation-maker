import { useId, useState } from "react";

import { fieldLabel, initialValues, inputsOf, settingsOf, type FieldValues } from "../lib/fields";
import type { AutomationSpec, SpecField } from "../types/spec";
import { FieldControl } from "./FieldControl";

type Screen = "run" | "setup";

interface Props {
  spec: AutomationSpec;
  /** Which screen to show first. */
  initialScreen?: Screen;
}

/**
 * The EXE window, drawn from the spec and filled with its sample_data. It follows the engine's
 * shell (ARCHITECTURE.md §8): first-time setup for settings, then the inputs form and Run.
 */
export default function SpecPreview({ spec, initialScreen = "run" }: Props) {
  const sample = (spec.sample_data ?? {}) as FieldValues;
  const settings = settingsOf(spec);
  const inputs = inputsOf(spec);

  const [screen, setScreen] = useState<Screen>(settings.length ? initialScreen : "run");
  const [settingValues, setSettingValues] = useState(() => initialValues(settings, sample));
  const [inputValues, setInputValues] = useState(() => initialValues(inputs, sample));
  const [ran, setRan] = useState(false);

  return (
    <figure
      aria-label={`Preview of the ${spec.title} app`}
      className="overflow-hidden rounded-lg border border-slate-300 bg-white font-win shadow-xl shadow-slate-900/10"
    >
      <WindowTitleBar title={spec.title} />

      {settings.length > 0 && (
        <div role="tablist" aria-label="Screens" className="flex gap-1 border-b border-slate-200 bg-slate-50 px-3 pt-2">
          <ScreenTab active={screen === "run"} onClick={() => setScreen("run")}>
            Fill in
          </ScreenTab>
          <ScreenTab active={screen === "setup"} onClick={() => setScreen("setup")}>
            Setup
          </ScreenTab>
        </div>
      )}

      <div className="space-y-4 p-4 sm:p-5">
        {screen === "setup" ? (
          <>
            <p className="text-sm text-slate-600">
              Entered once and saved on this PC. You can change them any time.
            </p>
            <FieldList fields={settings} values={settingValues} onChange={setSettingValues} />
            <div className="flex justify-end">
              <button
                type="button"
                className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500"
                onClick={() => setScreen("run")}
              >
                Save
              </button>
            </div>
          </>
        ) : (
          <>
            {inputs.length === 0 ? (
              <p className="text-sm text-slate-600">Nothing to fill in. Press Run to start.</p>
            ) : (
              <FieldList fields={inputs} values={inputValues} onChange={setInputValues} />
            )}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4">
              <p className="text-xs text-slate-500">Filled with sample data</p>
              <button
                type="button"
                className="rounded-md bg-indigo-600 px-5 py-2 text-sm font-semibold text-white hover:bg-indigo-500"
                onClick={() => setRan(true)}
              >
                Run
              </button>
            </div>
            {ran && (
              <p role="status" className="rounded-md bg-indigo-50 px-3 py-2 text-sm text-indigo-900">
                This is a preview. In the app, Run does the work on your PC and shows the result here.
              </p>
            )}
          </>
        )}
      </div>
    </figure>
  );
}

function FieldList({
  fields,
  values,
  onChange,
}: {
  fields: SpecField[];
  values: FieldValues;
  onChange: (values: FieldValues) => void;
}) {
  const baseId = useId();
  return (
    <div className="space-y-3.5">
      {fields.map((field) => {
        const id = `${baseId}-${field.key}`;
        const set = (value: unknown) => onChange({ ...values, [field.key]: value });
        const control = <FieldControl id={id} field={field} value={values[field.key]} onChange={set} />;

        if (field.type === "checkbox") {
          return (
            <div key={field.key} className="flex items-center gap-2">
              {control}
              <label htmlFor={id} className="text-sm text-slate-800">
                {fieldLabel(field)}
              </label>
            </div>
          );
        }
        return (
          <div key={field.key}>
            <label htmlFor={id} className="mb-1 block text-sm font-medium text-slate-800">
              {fieldLabel(field)}
              {field.required && (
                <span className="text-rose-600" aria-label="required">
                  {" "}
                  *
                </span>
              )}
            </label>
            {control}
            {field.help && <p className="mt-1 text-xs text-slate-500">{field.help}</p>}
          </div>
        );
      })}
    </div>
  );
}

function WindowTitleBar({ title }: { title: string }) {
  return (
    <div className="flex h-9 items-center justify-between border-b border-slate-200 bg-slate-100 pl-3 text-xs text-slate-700">
      <span className="flex min-w-0 items-center gap-2">
        <img src="/favicon.svg" alt="" className="h-4 w-4 shrink-0" />
        <span className="truncate">{title}</span>
      </span>
      <span aria-hidden className="flex h-full shrink-0 text-slate-500">
        <span className="flex w-11 items-center justify-center">─</span>
        <span className="flex w-11 items-center justify-center">☐</span>
        <span className="flex w-11 items-center justify-center">✕</span>
      </span>
    </div>
  );
}

function ScreenTab({ active, onClick, children }: { active: boolean; onClick: () => void; children: string }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`-mb-px rounded-t-md border px-3 py-1.5 text-sm ${
        active
          ? "border-slate-200 border-b-white bg-white font-semibold text-slate-900"
          : "border-transparent text-slate-600 hover:text-slate-900"
      }`}
    >
      {children}
    </button>
  );
}
