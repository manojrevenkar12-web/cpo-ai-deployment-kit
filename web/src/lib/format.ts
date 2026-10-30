export const pct = (x: number | null | undefined, digits = 0): string =>
  x == null ? "–" : `${(x * 100).toFixed(digits)}%`;

export const signedPct = (x: number | null | undefined): string =>
  x == null ? "–" : `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x * 100).toFixed(0)}%`;

export const eur = (x: number | null | undefined, digits = 0): string =>
  x == null
    ? "–"
    : new Intl.NumberFormat("en-GB", { style: "currency", currency: "EUR", maximumFractionDigits: digits, minimumFractionDigits: digits }).format(x);

export const num = (x: number | null | undefined, digits = 0): string =>
  x == null ? "–" : new Intl.NumberFormat("en-GB", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(x);

export const words = (id: string): string => id.replaceAll("_", " ");

export const COUNTRY: Record<string, string> = {
  AT: "Austria", CZ: "Czechia", DE: "Germany", DK: "Denmark", GB: "United Kingdom", HU: "Hungary",
  IT: "Italy", NL: "Netherlands", PL: "Poland", RO: "Romania", SE: "Sweden",
};
