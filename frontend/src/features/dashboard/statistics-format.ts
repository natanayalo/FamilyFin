import { formatAmount } from "./format";

/** Round presentation only; keep service decimals untouched in detailed statistics. */
export function formatStatisticAmount(value: string | null | undefined, currency: string) {
  if (value == null || !/^-?\d+(?:\.\d+)?$/.test(value)) return formatAmount(value, currency);
  const negative = value.startsWith("-");
  const [whole, fraction = ""] = (negative ? value.slice(1) : value).split(".");
  let cents = BigInt(whole) * BigInt(100) + BigInt(fraction.padEnd(2, "0").slice(0, 2));
  if (Number(fraction[2] ?? 0) >= 5) cents += BigInt(1);
  const digits = cents.toString().padStart(3, "0");
  return formatAmount(`${negative && cents !== BigInt(0) ? "-" : ""}${digits.slice(0, -2)}.${digits.slice(-2)}`, currency);
}
