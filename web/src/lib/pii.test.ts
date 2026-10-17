import { findPii, maskPii, verhoeffValid, type PiiKind } from "./pii";

const kinds = (text: string) => findPii(text).map((m) => [m.kind, m.text]);

describe("findPii", () => {
  it.each<[PiiKind, string]>([
    ["email", "asha.traders@gmail.com"],
    ["phone", "+91 98765 43210"],
    ["phone", "9876543210"],
    ["phone", "09876543210"],
    ["phone", "+44 20 7946 0958"],
    ["pan", "ABCPE1234F"],
    ["gstin", "27ABCPE1234F1Z5"],
    ["ifsc", "HDFC0001234"],
    ["card", "4111 1111 1111 1111"],
    ["card", "4111-1111-1111-1111"],
    ["aadhaar", "2341 2341 2346"],
    ["aadhaar", "234123412346"],
    ["bank_account", "50100012345678"],
  ])("finds %s in %j", (kind, value) => {
    expect(kinds(`Send it to ${value} please`)).toEqual([[kind, value]]);
  });

  it("prefers the GSTIN over the PAN inside it", () => {
    expect(kinds("GSTIN 27ABCPE1234F1Z5")).toEqual([["gstin", "27ABCPE1234F1Z5"]]);
  });

  it("does not call a 12-digit number Aadhaar unless the checksum matches", () => {
    expect(kinds("ref 234123412345")).toEqual([["bank_account", "234123412345"]]);
  });

  it("ignores format-only descriptions", () => {
    const text =
      "Invoice number like INV-0007, qty 2, rate 500, GST 18%. Customer name, phone and " +
      "email are typed in each time. Date as 17-10-2026.";
    expect(findPii(text)).toEqual([]);
  });

  it("finds several kinds in order", () => {
    expect(kinds("Call 9876543210 or mail a@b.co, PAN ABCPE1234F").map(([k]) => k)).toEqual([
      "phone",
      "email",
      "pan",
    ]);
  });
});

describe("maskPii", () => {
  it("replaces each match with a field placeholder", () => {
    expect(maskPii("Bill Asha (9876543210, asha@example.com) monthly")).toBe(
      "Bill Asha ([phone number], [email address]) monthly",
    );
  });

  it("leaves clean text unchanged", () => {
    expect(maskPii("Merge all PDFs in a folder")).toBe("Merge all PDFs in a folder");
  });
});

test("verhoeff", () => {
  expect(verhoeffValid("234123412346")).toBe(true);
  expect(verhoeffValid("234123412345")).toBe(false);
});
