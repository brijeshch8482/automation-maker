import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import invoice from "../../../automations/invoice-generator/spec.json";
import type { AutomationSpec } from "../types/spec";
import SpecPreview from "./SpecPreview";

const spec = invoice as unknown as AutomationSpec;

describe("SpecPreview with the invoice sample_data", () => {
  it("shows the inputs filled with sample data", () => {
    render(<SpecPreview spec={spec} />);
    expect(screen.getByLabelText(/Customer name/)).toHaveProperty("value", "Asha Traders");
    expect(screen.getByLabelText("Phone")).toHaveProperty("value", "");
    expect(screen.getByLabelText("GST %")).toHaveProperty("value", "18");

    const items = screen.getByRole("group", { name: "Items" });
    const headers = within(items).getAllByRole("columnheader").map((th) => th.textContent);
    expect(headers).toEqual(["Description", "Qty", "Rate", ""]);
    expect(within(items).getByDisplayValue("Sample item")).toBeTruthy();
    expect(within(items).getByDisplayValue("500")).toBeTruthy();
  });

  it("adds and removes table rows", async () => {
    const user = userEvent.setup();
    render(<SpecPreview spec={spec} />);
    const items = screen.getByRole("group", { name: "Items" });
    await user.click(within(items).getByRole("button", { name: "+ Add row" }));
    expect(within(items).getAllByRole("row")).toHaveLength(3); // header + 2 rows
    await user.click(within(items).getByRole("button", { name: "Remove row 1" }));
    await user.click(within(items).getByRole("button", { name: "Remove row 1" }));
    expect(within(items).getByText("No rows yet")).toBeTruthy();
  });

  it("shows settings on the Setup screen", async () => {
    const user = userEvent.setup();
    render(<SpecPreview spec={spec} />);
    await user.click(screen.getByRole("tab", { name: "Setup" }));
    expect(screen.getByLabelText(/Business name/)).toBeTruthy();
    expect(screen.getByLabelText("Save invoices to")).toHaveProperty("value", "No folder selected");
    expect(screen.getByRole("button", { name: "Choose folder…" })).toBeTruthy();
  });

  it("explains that Run is a preview", async () => {
    const user = userEvent.setup();
    render(<SpecPreview spec={spec} />);
    await user.click(screen.getByRole("button", { name: "Run" }));
    expect(screen.getByRole("status").textContent).toMatch(/This is a preview/);
  });

  it("renders every field type", () => {
    const allTypes: AutomationSpec = {
      ...spec,
      settings: [],
      inputs: [
        { key: "t", type: "text", label: "Text" },
        { key: "n", type: "number", label: "Number" },
        { key: "m", type: "money", label: "Money", currency: "USD" },
        { key: "p", type: "phone", label: "Phone" },
        { key: "e", type: "email", label: "Email" },
        { key: "d", type: "date", label: "Date" },
        { key: "f", type: "file", label: "File" },
        { key: "fs", type: "files", label: "Files" },
        { key: "fo", type: "folder", label: "Folder" },
        { key: "i", type: "image_file", label: "Image" },
        { key: "s", type: "select", label: "Select", options: ["A", "B"] },
        { key: "c", type: "checkbox", label: "Check" },
        { key: "tb", type: "table", label: "Table", columns: [{ key: "x", type: "text" }] },
      ],
      sample_data: { fs: ["a.pdf", "b.pdf"], c: true },
    };
    render(<SpecPreview spec={allTypes} />);
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.getByText("$")).toBeTruthy();
    expect(screen.getByLabelText("Files")).toHaveProperty("value", "2 files: a.pdf, b.pdf");
    expect(screen.getByLabelText("Check")).toHaveProperty("checked", true);
    expect(screen.getByLabelText("Date")).toHaveProperty("type", "date");
    expect(screen.getByRole("group", { name: "Table" })).toBeTruthy();
  });
});
