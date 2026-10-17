import cases from "../../../tests/fixtures/pii_cases.json";
import { findPii, maskPii, verhoeffValid } from "./pii";

// The same cases run against the server guard (api/src/api/pii.py).
describe("findPii (shared cases)", () => {
  it.each(cases.detect)("$text", ({ text, expect: expected }) => {
    expect(findPii(text).map((m) => [m.kind, m.text])).toEqual(expected);
  });
});

describe("maskPii (shared cases)", () => {
  it.each(cases.mask)("$text", ({ text, masked }) => {
    expect(maskPii(text)).toBe(masked);
  });
});

test("verhoeff", () => {
  expect(verhoeffValid("234123412346")).toBe(true);
  expect(verhoeffValid("234123412345")).toBe(false);
});
