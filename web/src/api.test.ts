import { ApiError, getAutomation, getJob, jobsAvailable, listAutomations } from "./api";
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

test("getAutomation maps 404 to null and keeps other errors", async () => {
  useApi();
  mockFetch(({ path }) => (path === "/automations/boom" ? { status: 500, body: {} } : undefined));
  expect(await getAutomation("nope")).toBeNull();
  await expect(getAutomation("boom")).rejects.toBeInstanceOf(ApiError);
});
