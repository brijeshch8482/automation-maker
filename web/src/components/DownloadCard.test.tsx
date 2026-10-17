import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { makeJob, mockFetch, renderAt, useApi } from "../test/helpers";
import { browser, formatSize } from "./DownloadCard";

const INFO = {
  version: "1.0.0",
  filename: "MakePDF.zip",
  size_bytes: 51_200_000,
  url: "https://acct.r2.cloudflarestorage.com/b/catalog/make-pdf/1.0.0/MakePDF.zip?X-Amz-Signature=abc",
  guide_url: "https://acct.r2.cloudflarestorage.com/b/catalog/make-pdf/1.0.0/Guide.pdf?X-Amz-Signature=def",
  expires_in: 900,
  built_at: "2026-10-17T11:00:00Z",
};

test("sizes read like a person would say them", () => {
  expect(formatSize(51_200_000)).toBe("51 MB");
  expect(formatSize(900_000)).toBe("900 KB");
  expect(formatSize(null)).toBeNull();
});

test("without the API, downloads are announced as coming", async () => {
  renderAt("/automations/make-pdf");
  expect(await screen.findByText(/Downloads open soon/)).toBeTruthy();
  expect(screen.getByRole("button", { name: /Download for Windows/ })).toHaveProperty("disabled", true);
});

test("not published yet (503): coming soon", async () => {
  useApi(null);
  mockFetch(({ path }) => (path === "/automations/make-pdf/download" ? { status: 503, body: { detail: "x" } } : undefined));
  renderAt("/automations/make-pdf");
  expect(await screen.findByText(/Downloads open soon/)).toBeTruthy();
});

test("published: size and version, then the download and what to do next", async () => {
  useApi(null);
  const calls = mockFetch(({ path }) => (path === "/automations/make-pdf/download" ? { body: INFO } : undefined));
  const open = vi.spyOn(browser, "open").mockImplementation(() => {});
  const user = userEvent.setup();
  renderAt("/automations/make-pdf");

  expect(await screen.findByText("51 MB · version 1.0.0")).toBeTruthy();
  expect(calls[0]?.auth).toBeNull(); // ready-made apps need no login
  expect(screen.getByRole("link", { name: /step-by-step guide/ })).toHaveProperty("href", INFO.guide_url);

  await user.click(screen.getByRole("button", { name: /Download for Windows/ }));
  expect(open).toHaveBeenCalledWith(INFO.url);
  const status = screen.getByText("Your download has started").parentElement!;
  expect(status.textContent).toContain("MakePDF.zip");
  expect(status.textContent).toContain("double-click MakePDF.exe");
  expect(status.textContent).toContain("Run anyway");
  open.mockRestore();
});

test("server unreachable: say so and let the user try again", async () => {
  useApi(null);
  let fail = true;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      if (fail) throw new TypeError("network down");
      return new Response(JSON.stringify(INFO), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  const user = userEvent.setup();
  renderAt("/automations/make-pdf");
  expect(await screen.findByText(/Couldn't reach our server/)).toBeTruthy();
  fail = false;
  await user.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("51 MB · version 1.0.0")).toBeTruthy();
});

test("a ready custom app links to its download and guide", async () => {
  useApi();
  const job = makeJob({
    state: "ready",
    download_url: "https://acct.r2.cloudflarestorage.com/b/jobs/job_01TEST/attempt-0/InvoiceGenerator.zip?X-Amz-Signature=a",
    guide_url: "https://acct.r2.cloudflarestorage.com/b/jobs/job_01TEST/attempt-0/Guide.pdf?X-Amz-Signature=b",
  });
  mockFetch(({ path }) => (path === "/jobs/job_01TEST" ? { body: job } : undefined));
  const user = userEvent.setup();
  renderAt("/jobs/job_01TEST");
  const download = await screen.findByRole("link", { name: "Download for Windows" });
  expect(download).toHaveProperty("href", job.download_url);
  expect(screen.getByRole("link", { name: "Read the guide (PDF)" })).toHaveProperty("href", job.guide_url);
  download.addEventListener("click", (e) => e.preventDefault()); // jsdom can't navigate
  await user.click(download);
  expect(screen.getByText("Your download has started").parentElement!.textContent).toContain("InvoiceGenerator.exe");
});
