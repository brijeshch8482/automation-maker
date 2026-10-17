import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { renderAt } from "./test/helpers";

// Without VITE_API_URL: bundled catalog, no custom jobs.

test("catalog links to the automation page", async () => {
  const user = userEvent.setup();
  renderAt("/");
  await user.click(await screen.findByRole("link", { name: /Invoice Generator/ }));
  expect(await screen.findByRole("heading", { level: 1, name: "Invoice Generator" })).toBeTruthy();
  expect(screen.getByRole("figure", { name: /Preview of the Invoice Generator app/ })).toBeTruthy();
  expect(screen.getAllByText("Works offline").length).toBeGreaterThan(0);
  expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
});

test("unknown automation shows not found", async () => {
  renderAt("/automations/nope");
  expect(await screen.findByText(/couldn't find that automation/)).toBeTruthy();
});

test("custom page warns about PII and masks it", async () => {
  const user = userEvent.setup();
  renderAt("/custom");
  const box = screen.getByLabelText("What should it do?");
  await user.type(box, "Send to 9876543210 each month");
  expect(screen.getByRole("alert").textContent).toMatch(/phone number/);
  await user.click(screen.getByRole("button", { name: "Mask all" }));
  expect(box).toHaveProperty("value", "Send to [phone number] each month");
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByRole("button", { name: "Design my automation" })).toHaveProperty("disabled", true);
  expect(screen.getByText("Custom builds open soon.")).toBeTruthy();
});

test("automations that rename files promise a preview and undo, not 'never changed'", async () => {
  renderAt("/automations/bulk-rename");
  expect(await screen.findByText(/renamed only after you check a preview/)).toBeTruthy();
  expect(screen.queryByText(/original files are never changed/)).toBeNull();
  expect(screen.getByLabelText(/Folder with the files/)).toHaveProperty("value", "Holiday photos");
});

test("PDF Merge keeps originals and lists file names", async () => {
  renderAt("/automations/pdf-merge");
  expect(await screen.findByText(/original files are never changed/)).toBeTruthy();
  expect(screen.getByLabelText(/PDF files, in order/)).toHaveProperty(
    "value",
    "2 files: Bill-March.pdf, Bill-April.pdf",
  );
});

test("Make PDF lists photos and PDFs and shows its options", async () => {
  renderAt("/automations/make-pdf");
  expect(await screen.findByText(/original files are never changed/)).toBeTruthy();
  expect(screen.getByLabelText(/Photos, screenshots or PDFs/)).toHaveProperty(
    "value",
    "3 files: Receipt photo.jpg, Screenshot.png, Notes.pdf",
  );
  expect(screen.getByLabelText("Page size")).toHaveProperty("value", "A4");
  expect(screen.getByLabelText(/Make the file smaller/)).toHaveProperty("checked", false);
});

test("home page explains the product and links to the catalog", async () => {
  renderAt("/");
  expect(screen.getByRole("heading", { level: 1, name: /your own Windows app/ })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "From task to app in three steps" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Your data stays on your PC" })).toBeTruthy();
  // The hero shows a live app preview; the featured list links to every automation.
  expect(await screen.findByRole("figure", { name: /Preview of the Make PDF app/ })).toBeTruthy();
  expect(screen.getByRole("link", { name: /Bulk Rename/ })).toHaveProperty("href", expect.stringContaining("/automations/bulk-rename"));
  expect(document.title).toBe("MakeMyEXE · Windows automations that run offline");
});

test("catalog search and category filter", async () => {
  const user = userEvent.setup();
  renderAt("/automations");
  expect(await screen.findByText("4 automations")).toBeTruthy();
  expect(document.title).toBe("Automations · MakeMyEXE");

  await user.click(screen.getByRole("button", { name: "PDF" }));
  expect(screen.getByText("2 of 4 automations")).toBeTruthy();
  expect(screen.getByRole("button", { name: "PDF" })).toHaveProperty("ariaPressed", "true");
  expect(screen.queryByRole("link", { name: /Bulk Rename/ })).toBeNull();

  await user.click(screen.getByRole("button", { name: "All" }));
  await user.type(screen.getByLabelText("Search automations"), "photos screenshots");
  expect(screen.getByText("1 of 4 automations")).toBeTruthy();
  expect(screen.getByRole("link", { name: /Make PDF/ })).toBeTruthy();

  await user.clear(screen.getByLabelText("Search automations"));
  await user.type(screen.getByLabelText("Search automations"), "payroll");
  expect(screen.getByText(/No automation matches “payroll”/)).toBeTruthy();
  expect(screen.getAllByRole("link", { name: /Request a custom app/ }).length).toBeGreaterThan(0);
});

test("mobile menu opens and closes on navigation", async () => {
  const user = userEvent.setup();
  renderAt("/");
  const toggle = screen.getByRole("button", { name: "Open menu" });
  expect(toggle).toHaveProperty("ariaExpanded", "false");
  await user.click(toggle);
  const menu = document.getElementById("mobile-menu")!;
  expect(within(menu).getByRole("link", { name: "Custom app" })).toBeTruthy();
  await user.click(within(menu).getByRole("link", { name: "Automations" }));
  expect(document.getElementById("mobile-menu")).toBeNull();
  expect(await screen.findByRole("heading", { level: 1, name: "Ready-made automations" })).toBeTruthy();
});

test("privacy and terms pages, linked from the footer", async () => {
  const user = userEvent.setup();
  renderAt("/");
  const footer = screen.getByRole("contentinfo");
  await user.click(within(footer).getByRole("link", { name: "Privacy" }));
  expect(screen.getByRole("heading", { level: 1, name: "Privacy" })).toBeTruthy();
  expect(screen.getByText(/description is deleted after 30 days/)).toBeTruthy();
  await user.click(within(screen.getByRole("contentinfo")).getByRole("link", { name: "Terms" }));
  expect(screen.getByRole("heading", { level: 1, name: "Terms of use" })).toBeTruthy();
  // Without VITE_CONTACT_EMAIL no address is shown.
  expect(screen.queryByText(/@/)).toBeNull();
});

test("contact address appears when configured", async () => {
  vi.stubEnv("VITE_CONTACT_EMAIL", "hello@makemyexe.test");
  renderAt("/privacy");
  expect(screen.getAllByRole("link", { name: "hello@makemyexe.test" }).length).toBe(2); // footer + page
});

test("automation page has a breadcrumb and its own title", async () => {
  renderAt("/automations/make-pdf");
  const crumb = await screen.findByRole("navigation", { name: "Breadcrumb" });
  expect(within(crumb).getByRole("link", { name: "Automations" })).toBeTruthy();
  expect(document.title).toBe("Make PDF · MakeMyEXE");
  expect(screen.getByRole("button", { name: /Download for Windows/ })).toHaveProperty("disabled", true);
});
