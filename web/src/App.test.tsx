import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";

import App from "./App";

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );

test("catalog links to the automation page", async () => {
  const user = userEvent.setup();
  renderAt("/");
  await user.click(await screen.findByRole("link", { name: /Invoice Generator/ }));
  expect(await screen.findByRole("heading", { level: 1, name: "Invoice Generator" })).toBeTruthy();
  expect(screen.getByRole("figure", { name: /Preview of the Invoice Generator app/ })).toBeTruthy();
  expect(screen.getAllByText("Works offline").length).toBeGreaterThan(0);
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
});
