import invoice from "../../../automations/invoice-generator/spec.json";
import type { AutomationSpec } from "../types/spec";
import { addField, moveField, removeField, setTitle, slugify, uniqueKey, updateField } from "./specEdit";

const spec = invoice as unknown as AutomationSpec;
const keys = (s: AutomationSpec, section: "settings" | "inputs") => (s[section] ?? []).map((f) => f.key);

test("slugify makes valid keys", () => {
  expect(slugify("Customer GST no.")).toBe("customer_gst_no");
  expect(slugify("  Due date ")).toBe("due_date");
  expect(slugify("2nd address")).toBe("field_2nd_address");
  expect(slugify("₹")).toBe("field");
});

test("uniqueKey avoids existing keys in settings and inputs", () => {
  expect(uniqueKey(spec, "Customer name")).toBe("customer_name_2");
  expect(uniqueKey(spec, "GSTIN")).toBe("gstin_2");
  expect(uniqueKey(spec, "Notes")).toBe("notes");
});

test("edits never mutate the original", () => {
  const before = JSON.stringify(spec);
  setTitle(spec, "X");
  updateField(spec, "inputs", 0, { label: "Client" });
  moveField(spec, "inputs", 0, 1);
  removeField(spec, "inputs", 0);
  addField(spec, "inputs", { label: "Notes", type: "text" });
  expect(JSON.stringify(spec)).toBe(before);
});

test("updateField changes label and required", () => {
  const next = updateField(spec, "inputs", 1, { label: "Mobile", required: true });
  expect(next.inputs?.[1]).toMatchObject({ key: "customer_phone", label: "Mobile", required: true });
});

test("moveField swaps neighbours and ignores moves past the ends", () => {
  expect(keys(moveField(spec, "inputs", 0, 1), "inputs").slice(0, 2)).toEqual([
    "customer_phone",
    "customer_name",
  ]);
  expect(moveField(spec, "inputs", 0, -1)).toBe(spec);
});

test("removeField drops the field and its sample data", () => {
  const next = removeField(spec, "inputs", 0);
  expect(keys(next, "inputs")).not.toContain("customer_name");
  expect(next.sample_data).not.toHaveProperty("customer_name");
  expect(next.sample_data).toHaveProperty("items");
});

test("addField appends with a unique key", () => {
  const next = addField(spec, "settings", { label: "Bank details", type: "text" });
  expect(next.settings?.at(-1)).toEqual({ key: "bank_details", label: "Bank details", type: "text" });
  const select = addField(spec, "inputs", { label: "Payment", type: "select", options: ["Cash", "UPI"] });
  expect(select.inputs?.at(-1)).toMatchObject({ type: "select", options: ["Cash", "UPI"] });
});
