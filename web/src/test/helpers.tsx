import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

import App from "../App";
import type { Job } from "../api";
import { AuthProvider } from "../auth";
import invoice from "../../../automations/invoice-generator/spec.json";
import type { AutomationSpec } from "../types/spec";

export const API = "http://api.test";
export const invoiceSpec = invoice as unknown as AutomationSpec;

export function renderAt(path: string, state?: unknown) {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[{ pathname: path.split("?")[0], search: path.includes("?") ? `?${path.split("?")[1]}` : "", state }]}>
        <App />
      </MemoryRouter>
    </AuthProvider>,
  );
}

/** Turn on the API and dev login; optionally sign in as `user`. */
export function useApi(user: string | null = "alice") {
  vi.stubEnv("VITE_API_URL", API);
  vi.stubEnv("VITE_DEV_AUTH", "true");
  if (user) localStorage.setItem("makemyexe.devUser", user);
  else localStorage.removeItem("makemyexe.devUser");
}

export interface Call {
  method: string;
  path: string;
  body: unknown;
  auth: string | null;
}

type Handler = (call: Call) => { status?: number; body?: unknown } | undefined;

/** Stub fetch with a small router. Returns the list of calls made. */
export function mockFetch(handler: Handler): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const headers = (init.headers ?? {}) as Record<string, string>;
      const call: Call = {
        method: init.method ?? "GET",
        path: url.replace(API, ""),
        body: init.body ? JSON.parse(init.body as string) : undefined,
        auth: headers.Authorization ?? null,
      };
      calls.push(call);
      const result = handler(call) ?? { status: 404, body: { detail: "not found" } };
      const status = result.status ?? 200;
      return new Response(status === 204 ? null : JSON.stringify(result.body ?? null), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

export function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "job_01TEST",
    state: "spec_ready",
    description: "Make invoices from customer and item details",
    spec: invoiceSpec,
    assumptions: ["GST is 18% unless changed"],
    questions: ["Do you need a discount column?"],
    revision: 0,
    attempt: 0,
    failure_reason: null,
    run_url: null,
    download_url: null,
    guide_url: null,
    created_at: "2026-10-17T09:00:00Z",
    updated_at: "2026-10-17T09:05:00Z",
    attempts: [
      {
        mode: "spec",
        revision: 0,
        attempt: 0,
        status: "ok",
        session_url: "https://claude.ai/code/session_1",
        created_at: "2026-10-17T09:00:00Z",
      },
    ],
    ...overrides,
  };
}
