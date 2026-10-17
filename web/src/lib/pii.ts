// Browser-side PII guard for custom-automation descriptions (ARCHITECTURE.md §3, Flow B).
// We only need the FORMAT of a task, so anything that looks like real personal or business
// data is flagged and can be masked before the description is sent. FastAPI repeats the check.

export type PiiKind =
  | "email"
  | "gstin"
  | "pan"
  | "ifsc"
  | "card"
  | "aadhaar"
  | "phone"
  | "bank_account";

export interface PiiMatch {
  kind: PiiKind;
  start: number;
  end: number;
  text: string;
}

export const PII_LABELS: Record<PiiKind, string> = {
  email: "email address",
  gstin: "GSTIN",
  pan: "PAN",
  ifsc: "IFSC code",
  card: "card number",
  aadhaar: "Aadhaar number",
  phone: "phone number",
  bank_account: "bank account number",
};

const digitsOf = (s: string) => s.replace(/\D/g, "");

function luhnValid(digits: string): boolean {
  let sum = 0;
  for (let i = 0; i < digits.length; i++) {
    let d = Number(digits[digits.length - 1 - i]);
    if (i % 2 === 1) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    sum += d;
  }
  return sum % 10 === 0;
}

// Verhoeff checksum, used by Aadhaar numbers.
const VERHOEFF_D = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
  [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
  [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
  [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
  [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
  [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
  [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
  [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
  [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
  [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
];
const VERHOEFF_P = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
  [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
  [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
  [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
  [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
  [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
  [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
  [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
];

export function verhoeffValid(digits: string): boolean {
  let c = 0;
  const reversed = [...digits].reverse();
  reversed.forEach((ch, i) => {
    c = VERHOEFF_D[c]![VERHOEFF_P[i % 8]![Number(ch)]!]!;
  });
  return c === 0;
}

interface Detector {
  kind: PiiKind;
  pattern: RegExp;
  accept?: (text: string) => boolean;
}

// Order matters: earlier detectors win where matches overlap (a GSTIN contains a PAN,
// a card or Aadhaar number would also match the generic bank-account pattern).
const DETECTORS: Detector[] = [
  { kind: "email", pattern: /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}/g },
  { kind: "gstin", pattern: /\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b/gi },
  { kind: "pan", pattern: /\b[A-Z]{3}[ABCFGHJLPT][A-Z]\d{4}[A-Z]\b/gi },
  { kind: "ifsc", pattern: /\b[A-Z]{4}0[A-Z0-9]{6}\b/gi },
  {
    kind: "card",
    pattern: /(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])/g,
    accept: (t) => luhnValid(digitsOf(t)),
  },
  {
    kind: "aadhaar",
    pattern: /(?<!\d)[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?!\d)/g,
    accept: (t) => verhoeffValid(digitsOf(t)),
  },
  {
    kind: "phone",
    pattern: /(?<![\w+])(?:(?:\+91|0091|91)[ -]?|0)?[6-9]\d{4}[ -]?\d{5}(?!\d)|\+\d{1,3}[ -]?\d(?:[ -]?\d){6,12}(?!\d)/g,
  },
  { kind: "bank_account", pattern: /(?<!\d)\d{9,18}(?!\d)/g },
];

export function findPii(text: string): PiiMatch[] {
  const found: PiiMatch[] = [];
  const overlaps = (start: number, end: number) =>
    found.some((m) => start < m.end && m.start < end);

  for (const { kind, pattern, accept } of DETECTORS) {
    for (const match of text.matchAll(pattern)) {
      const start = match.index;
      const end = start + match[0].length;
      if (overlaps(start, end) || (accept && !accept(match[0]))) continue;
      found.push({ kind, start, end, text: match[0] });
    }
  }
  return found.sort((a, b) => a.start - b.start);
}

/** Replace every match with a placeholder such as "[phone number]". */
export function maskPii(text: string, matches: PiiMatch[] = findPii(text)): string {
  let out = "";
  let last = 0;
  for (const m of [...matches].sort((a, b) => a.start - b.start)) {
    out += `${text.slice(last, m.start)}[${PII_LABELS[m.kind]}]`;
    last = m.end;
  }
  return out + text.slice(last);
}
