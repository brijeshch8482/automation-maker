// Data access for the web app. Every page goes through here.
//
// With VITE_API_URL set, everything comes from the FastAPI service (ARCHITECTURE.md §10).
// Without it, the catalog is read from automations/*/spec.json at build time and custom jobs
// are unavailable.

import { getAccessToken } from "./auth";
import { apiUrl } from "./env";
import type { AutomationSpec } from "./types/spec";

export type AutomationSummary = Pick<
  AutomationSpec,
  "id" | "title" | "description" | "category" | "version" | "network"
>;

export type JobState =
  | "draft"
  | "spec_requested"
  | "spec_ready"
  | "queued"
  | "generating"
  | "building"
  | "repairing"
  | "ready"
  | "failed"
  | "expired";

export interface JobAttempt {
  mode: "spec" | "build" | "repair";
  revision: number;
  attempt: number;
  status: string;
  session_url: string | null;
  created_at: string;
}

export interface Job {
  id: string;
  state: JobState;
  description: string | null;
  spec: AutomationSpec | null;
  assumptions: string[];
  questions: string[];
  revision: number;
  attempt: number;
  failure_reason: string | null;
  run_url: string | null;
  download_url: string | null;
  guide_url: string | null;
  created_at: string;
  updated_at: string;
  attempts: JobAttempt[];
}

export interface JobSummary {
  id: string;
  state: JobState;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface Answer {
  question: string;
  answer: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly issues: string[] = [],
  ) {
    super(message);
  }
}

/** Custom jobs need the API. */
export function jobsAvailable(): boolean {
  return apiUrl() !== "";
}

async function request<T>(
  path: string,
  { method = "GET", body, auth = false }: { method?: string; body?: unknown; auth?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth) {
    const token = await getAccessToken();
    if (!token) throw new ApiError(401, "Please sign in first.");
    headers.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${apiUrl()}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }
  if (response.ok) return (response.status === 204 ? undefined : await response.json()) as T;

  const data = await response.json().catch(() => null);
  const detail = data?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    throw new ApiError(response.status, detail.message ?? "Request failed", detail.issues ?? []);
  }
  throw new ApiError(response.status, typeof detail === "string" ? detail : messageFor(response.status));
}

function messageFor(status: number): string {
  if (status === 401) return "Please sign in again.";
  if (status === 404) return "Not found.";
  if (status === 409) return "This changed in the meantime. Refresh and try again.";
  if (status === 422) return "Some of the details aren't valid.";
  return "Something went wrong on our side. Please try again.";
}

// --- Catalog --------------------------------------------------------------------------

const specFiles = import.meta.glob<AutomationSpec>("../../automations/*/spec.json", {
  eager: true,
  import: "default",
});

const BUNDLED: AutomationSpec[] = Object.values(specFiles).sort((a, b) =>
  a.title.localeCompare(b.title),
);

// The ready-made catalog ships with the site (same repo, same deploy as the API's copy), so its
// pages render at once instead of waiting for a sleeping free-tier API to wake up.
export async function listAutomations(): Promise<AutomationSummary[]> {
  return BUNDLED;
}

export async function getAutomation(id: string): Promise<AutomationSpec | null> {
  return BUNDLED.find((spec) => spec.id === id) ?? null;
}

// --- Downloads ---------------------------------------------------------------------------

/** Short-lived links to the latest published build of a ready-made automation. */
export interface DownloadInfo {
  version: string;
  filename: string;
  size_bytes: number | null;
  url: string;
  guide_url: string;
  expires_in: number;
  built_at: string | null;
}

/** Null when downloads aren't published yet (or the site runs without the API). */
export async function getDownload(id: string): Promise<DownloadInfo | null> {
  if (!apiUrl()) return null;
  try {
    return await request<DownloadInfo>(`/automations/${encodeURIComponent(id)}/download`);
  } catch (err) {
    if (err instanceof ApiError && (err.status === 503 || err.status === 404)) return null;
    throw err;
  }
}

/** The same automation as a .mmx bundle for the installed MakeMyEXE app. Null until published. */
export async function getBundle(id: string): Promise<DownloadInfo | null> {
  if (!apiUrl()) return null;
  try {
    return await request<DownloadInfo>(`/automations/${encodeURIComponent(id)}/bundle`);
  } catch (err) {
    if (err instanceof ApiError && (err.status === 503 || err.status === 404)) return null;
    throw err;
  }
}

/** The MakeMyEXE installer (a short-lived link). */
export interface AppDownloadInfo {
  version: string;
  filename: string;
  size_bytes: number | null;
  sha256: string | null;
  url: string;
  expires_in: number;
}

/** Null until the first app release (or without the API). */
export async function getLatestApp(): Promise<AppDownloadInfo | null> {
  if (!apiUrl()) return null;
  try {
    return await request<AppDownloadInfo>("/app/latest");
  } catch (err) {
    if (err instanceof ApiError && (err.status === 503 || err.status === 404)) return null;
    throw err;
  }
}

// --- Jobs -----------------------------------------------------------------------------

const jobPath = (id: string) => `/jobs/${encodeURIComponent(id)}`;

export async function createJob(description: string): Promise<string> {
  const { job_id } = await request<{ job_id: string }>("/jobs", {
    method: "POST",
    body: { description },
    auth: true,
  });
  return job_id;
}

export function getJob(id: string): Promise<Job> {
  return request<Job>(jobPath(id), { auth: true });
}

export function answerQuestions(id: string, answers: Answer[]): Promise<Job> {
  return request<Job>(`${jobPath(id)}/answers`, { method: "POST", body: { answers }, auth: true });
}

export function saveSpec(id: string, spec: AutomationSpec): Promise<Job> {
  return request<Job>(`${jobPath(id)}/spec`, { method: "PUT", body: { spec }, auth: true });
}

export function confirmJob(id: string): Promise<Job> {
  return request<Job>(`${jobPath(id)}/confirm`, { method: "POST", auth: true });
}

export function listMyJobs(): Promise<JobSummary[]> {
  return request<JobSummary[]>("/me/jobs", { auth: true });
}
