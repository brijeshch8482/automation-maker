// Data access for the web app. Every page goes through here.
//
// Until the FastAPI service exists (Phase 3), the catalog is read from automations/*/spec.json
// at build time. When it does, these functions switch to GET /automations and
// GET /automations/{id}; the signatures stay the same.

import type { AutomationSpec } from "./types/spec";

const specFiles = import.meta.glob<AutomationSpec>("../../automations/*/spec.json", {
  eager: true,
  import: "default",
});

const CATALOG: AutomationSpec[] = Object.values(specFiles).sort((a, b) =>
  a.title.localeCompare(b.title),
);

export async function listAutomations(): Promise<AutomationSpec[]> {
  return CATALOG;
}

export async function getAutomation(id: string): Promise<AutomationSpec | null> {
  return CATALOG.find((spec) => spec.id === id) ?? null;
}
