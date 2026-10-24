// English number formatting for the training views ("1,024", "12.5").
const formats = new Map<number, Intl.NumberFormat>();

export function fmtNum(v: number, digits = 0): string {
  let f = formats.get(digits);
  if (!f) {
    f = new Intl.NumberFormat("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
    formats.set(digits, f);
  }
  return f.format(v);
}

/** A controller gain with as many decimals as it needs. */
export const fmtGain = (v: number) => fmtNum(v, v >= 100 ? 0 : v >= 10 ? 1 : 2);
