import { getAutomation, listAutomations } from "./api";

test("the catalog includes every automation with a description", async () => {
  const specs = await listAutomations();
  expect(specs.map((s) => s.id)).toContain("invoice-generator");
  for (const spec of specs) expect(spec.description).toBeTruthy();
});

test("getAutomation", async () => {
  expect((await getAutomation("invoice-generator"))?.title).toBe("Invoice Generator");
  expect(await getAutomation("nope")).toBeNull();
});
