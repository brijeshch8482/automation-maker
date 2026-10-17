import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

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
