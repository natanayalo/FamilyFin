import { describe, expect, it } from "vitest";
import { formatAmount, formatHebrewDate, formatHebrewDateTime, formatHebrewMonth, formatPercent, percentToRate, rateToPercent } from "@/lib/display";

describe("financial display boundaries", () => {
  it("groups money without losing service decimal precision", () => {
    expect(formatAmount("12345678901234567890.0010")).toBe("\u2067\u206612,345,678,901,234,567,890.0010\u2069 ש״ח\u2069");
    expect(formatAmount("-1234.50", "USD")).toBe("\u2067\u2066-1,234.50\u2069 $\u2069");
    expect(formatAmount("0.00")).toBe("\u2067\u20660.00\u2069 ש״ח\u2069");
    expect(formatAmount(null)).toBe("לא זמין");
  });
  it.each(["-119", "-350.1", "-29", "-2977", "-76", "0", "35892.82"])("isolates the sign and number from Hebrew currency: %s", (amount) => {
    const formatted = formatAmount(amount);
    expect(formatted.startsWith("\u2067\u2066")).toBe(true);
    expect(formatted.endsWith("\u2069 ש״ח\u2069")).toBe(true);
    const numericRun = formatted.slice(2, formatted.indexOf("\u2069"));
    expect(numericRun.replaceAll(",", "")).toBe(amount);
  });
  it("keeps foreign and custom currencies in the same Hebrew reading order", () => {
    expect(formatAmount("-350.10", "EUR")).toBe("\u2067\u2066-350.10\u2069 €\u2069");
    expect(formatAmount("12.0000", "GBP")).toBe("\u2067\u206612.0000\u2069 £\u2069");
    expect(formatAmount("1234.50", "CAD")).toBe("\u2067\u20661,234.50\u2069 CAD\u2069");
    expect(formatAmount("")).toBe("לא הוזן");
  });
  it.each([
    ["0", "0"], ["0.03", "3"], ["0.06", "6"], ["0.035", "3.5"],
    ["-0.005", "-0.5"], ["1", "100"], ["3.5025", "350.25"],
    ["0.000000000000001234", "0.0000000000001234"],
  ])("converts rate %s to percent %s and back exactly", (rate, percent) => {
    expect(rateToPercent(rate)).toBe(percent);
    expect(percentToRate(percent)).toBe(rate);
  });
  it("handles percentage entry and missing ratios", () => {
    expect(percentToRate(" .5% ")).toBe("0.005");
    expect(percentToRate("003.50")).toBe("0.035");
    expect(formatPercent("0.125")).toBe("12.5%");
    expect(formatPercent("0.616277777777777777")).toBe("61.63%");
    expect(formatPercent(null)).toBe("לא זמין");
  });

  it("formats Hebrew Gregorian dates and keeps date-only values free of times", () => {
    expect(formatHebrewMonth("2026-09-01")).toBe("ספטמבר 2026");
    expect(formatHebrewMonth("2026-09")).toBe("ספטמבר 2026");
    expect(formatHebrewDate("2026-08-31")).toBe("31 באוגוסט 2026");
    expect(formatHebrewDate("2026-02-31")).toBe("2026-02-31");
    expect(formatHebrewDateTime("20260920T120000Z")).toBe("20260920T120000Z");
  });
});
