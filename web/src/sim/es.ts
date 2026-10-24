// The evolution strategy: a cross-entropy method in the normalised [0, 1] parameter box.
// Sample a population around the mean, keep the elite quarter, move mean and spread there.
import { mulberry32 } from "./drone";
import type { ParamSpec, Params } from "./types";

export function toParams(specs: ParamSpec[], x: number[]): Params {
  const out: Params = {};
  specs.forEach((s, i) => {
    const u = Math.min(1, Math.max(0, x[i]));
    out[s.name] = s.log ? s.min * Math.pow(s.max / s.min, u) : s.min + (s.max - s.min) * u;
  });
  return out;
}

export function fromParams(specs: ParamSpec[], p: Params): number[] {
  return specs.map((s) => {
    const v = p[s.name] ?? s.init;
    return s.log ? Math.log(v / s.min) / Math.log(s.max / s.min) : (v - s.min) / (s.max - s.min);
  });
}

export class CrossEntropy {
  mean: number[];
  sigma: number[];
  private rnd: () => number;
  constructor(
    specs: ParamSpec[],
    seed = 7,
    sigma0 = 0.3,
    private eliteFrac = 0.25,
  ) {
    this.mean = fromParams(specs, Object.fromEntries(specs.map((s) => [s.name, s.init])));
    this.sigma = specs.map(() => sigma0);
    this.rnd = mulberry32(seed);
  }
  private gauss() {
    const u = Math.max(1e-12, this.rnd());
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * this.rnd());
  }
  /** `n` candidates in the unit box; the first one is the current mean. */
  ask(n: number): number[][] {
    const out: number[][] = [this.mean.map((m) => Math.min(1, Math.max(0, m)))];
    while (out.length < n) out.push(this.mean.map((m, i) => Math.min(1, Math.max(0, m + this.sigma[i] * this.gauss()))));
    return out;
  }
  tell(xs: number[][], scores: number[]) {
    const order = scores.map((s, i) => [s, i] as const).sort((a, b) => b[0] - a[0]);
    const k = Math.max(2, Math.round(xs.length * this.eliteFrac));
    const elite = order.slice(0, k).map(([, i]) => xs[i]);
    const dim = this.mean.length;
    for (let j = 0; j < dim; j++) {
      const mu = elite.reduce((a, x) => a + x[j], 0) / k;
      const varj = elite.reduce((a, x) => a + (x[j] - mu) ** 2, 0) / k;
      this.mean[j] = mu;
      // Smoothed, with a floor, so the search keeps exploring to the last generation.
      this.sigma[j] = Math.max(0.02, 0.6 * Math.sqrt(varj) + 0.4 * this.sigma[j] * 0.7);
    }
  }
}
