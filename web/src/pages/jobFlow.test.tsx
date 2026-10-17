import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { invoiceSpec, makeJob, mockFetch, renderAt, useApi } from "../test/helpers";
import { SpecReview } from "./JobPage";

describe("with the API", () => {
  test("the catalog renders without calling the API", async () => {
    useApi(null);
    const calls = mockFetch(() => undefined);
    renderAt("/automations");
    expect(await screen.findByRole("link", { name: /Make PDF/ })).toBeTruthy();
    expect(calls).toHaveLength(0);
  });

  test("custom page asks signed-out users to sign in", async () => {
    useApi(null);
    renderAt("/custom");
    expect(screen.getByRole("link", { name: "Sign in to continue" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Sign in" })).toBeTruthy(); // header
  });

  test("dev login returns to the page that asked for it", async () => {
    useApi(null);
    mockFetch(({ path }) => (path === "/me/jobs" ? { body: [] } : undefined));
    const user = userEvent.setup();
    renderAt("/login?next=/me/jobs");
    await user.type(screen.getByLabelText("Dev user name"), "alice");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText(/No custom automations yet/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Account" }).textContent).toBe("a"); // header menu
  });

  test("submitting a description creates a job and opens it", async () => {
    useApi();
    const calls = mockFetch(({ method, path }) => {
      if (method === "POST" && path === "/jobs") return { status: 202, body: { job_id: "job_01TEST" } };
      if (path === "/jobs/job_01TEST") {
        return { body: makeJob({ state: "spec_requested", spec: null, assumptions: [], questions: [] }) };
      }
      return undefined;
    });
    const user = userEvent.setup();
    renderAt("/custom");
    const submit = screen.getByRole("button", { name: "Design my automation" });
    expect(submit).toHaveProperty("disabled", true); // too short

    await user.type(screen.getByLabelText("What should it do?"), "Invoices to 9876543210");
    expect(submit).toHaveProperty("disabled", true); // PII must be masked first
    await user.click(screen.getByRole("button", { name: "Mask all" }));
    await user.click(submit);

    expect(await screen.findByText("Designing your automation")).toBeTruthy();
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({ description: "Invoices to [phone number]" });
    expect(post.auth).toBe("Bearer dev:alice");
    expect(screen.getByRole("listitem", { current: "step" }).textContent).toContain("Design");
  });

  test("reviewing a spec: edit, save, then build", async () => {
    useApi();
    let job = makeJob();
    const calls = mockFetch(({ method, path, body }) => {
      if (method === "PUT" && path === "/jobs/job_01TEST/spec") {
        job = makeJob({ spec: (body as { spec: typeof invoiceSpec }).spec });
        return { body: job };
      }
      if (method === "POST" && path === "/jobs/job_01TEST/confirm") {
        job = makeJob({ state: "generating" });
        return { status: 202, body: job };
      }
      if (path === "/jobs/job_01TEST") return { body: job };
      return undefined;
    });
    const user = userEvent.setup();
    renderAt("/jobs/job_01TEST");

    expect(await screen.findByText("GST is 18% unless changed")).toBeTruthy();
    expect(screen.getByLabelText("Do you need a discount column?")).toBeTruthy();
    const build = screen.getByRole("button", { name: "Build my app" });

    const label = screen.getByLabelText("Label for Phone") as HTMLInputElement;
    // Type over the selected old text in one step (clear-then-type can race on a busy runner).
    await user.type(label, "Mobile", { initialSelectionStart: 0, initialSelectionEnd: label.value.length });
    expect(build).toHaveProperty("disabled", true); // unsaved changes
    const preview = screen.getByRole("figure");
    expect(within(preview).getByLabelText("Mobile")).toBeTruthy(); // live preview

    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(build).toHaveProperty("disabled", false));
    const put = calls.find((c) => c.method === "PUT")!;
    const saved = (put.body as { spec: typeof invoiceSpec }).spec;
    expect(saved.inputs?.find((f) => f.key === "customer_phone")?.label).toBe("Mobile");

    await user.click(build);
    expect(await screen.findByText("Generating your app")).toBeTruthy();
  });

  test("save shows validation issues from the server", async () => {
    useApi();
    mockFetch(({ method, path }) => {
      if (method === "PUT") {
        return {
          status: 422,
          body: { detail: { message: "spec is not valid", issues: ["steps[1].args.table: 'items' is not an input key"] } },
        };
      }
      if (path === "/jobs/job_01TEST") return { body: makeJob() };
      return undefined;
    });
    const user = userEvent.setup();
    renderAt("/jobs/job_01TEST");
    await user.click(await screen.findByRole("button", { name: "Remove Items" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/'items' is not an input key/)).toBeTruthy();
    expect(screen.getByText("These changes can't be saved yet")).toBeTruthy();
    expect(screen.getByText(/still uses a field you removed/)).toBeTruthy();
  });

  test("answering questions masks PII and starts a revision", async () => {
    useApi();
    const calls = mockFetch(({ method, path }) => {
      if (method === "POST" && path === "/jobs/job_01TEST/answers") {
        return { status: 202, body: makeJob({ state: "spec_requested", revision: 1 }) };
      }
      if (path === "/jobs/job_01TEST") return { body: makeJob() };
      return undefined;
    });
    const user = userEvent.setup();
    renderAt("/jobs/job_01TEST");
    const answer = await screen.findByLabelText("Do you need a discount column?");
    const send = screen.getByRole("button", { name: "Update the design" });
    expect(send).toHaveProperty("disabled", true);
    await user.type(answer, "Yes, ask 9876543210");
    expect(send).toHaveProperty("disabled", true);
    await user.click(screen.getByRole("button", { name: "Mask all" }));
    await user.click(send);
    expect(await screen.findByText("Updating the design with your answers")).toBeTruthy();
    expect(calls.find((c) => c.path.endsWith("/answers"))?.body).toEqual({
      answers: [{ question: "Do you need a discount column?", answer: "Yes, ask [phone number]" }],
    });
  });

  test("ready, failed and expired jobs", async () => {
    useApi();
    let job = makeJob({ state: "ready" });
    mockFetch(({ path }) => (path === "/jobs/job_01TEST" ? { body: job } : undefined));
    const { unmount } = renderAt("/jobs/job_01TEST");
    expect(await screen.findByText("Your app is ready")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Download for Windows" })).toHaveProperty("disabled", true);
    unmount();

    job = makeJob({ state: "ready", download_url: "https://dl.test/app.zip" });
    const ready = renderAt("/jobs/job_01TEST");
    expect((await screen.findByRole("link", { name: "Download for Windows" })).getAttribute("href")).toBe(
      "https://dl.test/app.zip",
    );
    ready.unmount();

    job = makeJob({ state: "failed", failure_reason: "no result from the spec run within 15 minutes" });
    const user = userEvent.setup();
    renderAt("/jobs/job_01TEST");
    expect(await screen.findByText("No result from the spec run within 15 minutes.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "View session" }).getAttribute("href")).toBe(
      "https://claude.ai/code/session_1",
    );
    await user.click(screen.getByRole("button", { name: "Try again with the same description" }));
    expect(screen.getByLabelText("What should it do?")).toHaveProperty(
      "value",
      "Make invoices from customer and item details",
    );
  });

  test("a job that isn't yours shows not found", async () => {
    useApi();
    mockFetch(() => undefined);
    renderAt("/jobs/job_OTHER");
    expect(await screen.findByText(/couldn't find that job/)).toBeTruthy();
  });

  test("my automations lists jobs", async () => {
    useApi();
    mockFetch(({ path }) =>
      path === "/me/jobs"
        ? {
            body: [
              { id: "job_1", state: "building", title: "Invoice Generator", created_at: "2026-10-17T09:00:00Z", updated_at: "2026-10-17T09:10:00Z" },
              { id: "job_2", state: "spec_requested", title: null, created_at: "2026-10-17T08:00:00Z", updated_at: "2026-10-17T08:00:00Z" },
            ],
          }
        : undefined,
    );
    renderAt("/me/jobs");
    const first = await screen.findByRole("link", { name: /Invoice Generator/ });
    expect(first.getAttribute("href")).toBe("/jobs/job_1");
    expect(within(first).getByText("Building")).toBeTruthy();
    expect(screen.getByText("Untitled automation")).toBeTruthy();
  });

  test("server errors are shown in plain words", async () => {
    useApi();
    mockFetch(({ method }) => (method === "POST" ? { status: 500, body: {} } : undefined));
    const user = userEvent.setup();
    renderAt("/custom");
    await user.type(screen.getByLabelText("What should it do?"), "Merge all PDFs in a folder");
    await user.click(screen.getByRole("button", { name: "Design my automation" }));
    expect(await screen.findByText(/Something went wrong on our side/)).toBeTruthy();
  });
});


test("a fresh copy of the same design keeps edits in progress; a new design replaces them", async () => {
  const user = userEvent.setup();
  const job = makeJob();
  const spec = job.spec!;
  const { rerender } = render(<SpecReview job={job} spec={spec} onJob={() => {}} />);
  const label = screen.getByLabelText("Label for Phone") as HTMLInputElement;
  await user.type(label, "Mobile", { initialSelectionStart: 0, initialSelectionEnd: label.value.length });

  // What a reload returns: equal content, new object.
  rerender(<SpecReview job={job} spec={structuredClone(spec)} onJob={() => {}} />);
  expect(screen.getByLabelText("Label for Mobile")).toHaveProperty("value", "Mobile");
  expect(screen.getByRole("button", { name: "Save changes" })).toHaveProperty("disabled", false);

  const revised = { ...structuredClone(spec), title: "Invoice Maker" };
  rerender(<SpecReview job={job} spec={revised} onJob={() => {}} />);
  expect(screen.getByLabelText("Label for Phone")).toHaveProperty("value", "Phone");
  expect(screen.getByLabelText("App name")).toHaveProperty("value", "Invoice Maker");
});
