import { getAutomation, getJob, jobsAvailable, listAutomations } from "./api";
import { mockFetch, useApi } from "./test/helpers";

test("bundled catalog without the API", async () => {
  expect(jobsAvailable()).toBe(false);
  const specs = await listAutomations();
  expect(specs.map((s) => s.id)).toContain("invoice-generator");
  for (const spec of specs) expect(spec.description).toBeTruthy();
  expect((await getAutomation("invoice-generator"))?.title).toBe("Invoice Generator");
  expect(await getAutomation("nope")).toBeNull();
});

test("job calls need a login", async () => {
  useApi(null);
  mockFetch(() => ({ body: {} }));
  await expect(getJob("job_1")).rejects.toMatchObject({ status: 401 });
});

test("the catalog is bundled even with the API, so it never waits for it", async () => {
  useApi();
  const calls = mockFetch(() => ({ status: 500, body: {} }));
  expect((await listAutomations()).length).toBeGreaterThan(0);
  expect((await getAutomation("make-pdf"))?.title).toBe("Make PDF");
  expect(await getAutomation("nope")).toBeNull();
  expect(calls).toHaveLength(0);
});
