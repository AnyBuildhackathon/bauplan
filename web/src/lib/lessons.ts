// "Explain this": one concept per step, explained with the live numbers of the
// current build and checked with one question.
import type { MetricsEvent, StepId } from "../events/types";
import { fmtGram, fmtMin, fmtRatio } from "./format";

export type Diagram = "requirements" | "thrust" | "frame" | "render" | "reward" | "budget";

export interface Lesson {
  step: StepId;
  concept: string;
  body: string;
  diagram: Diagram;
  formula: (m: MetricsEvent | null) => { left: string; right: string };
  question: string;
  options: string[];
  correct: number;
  right: string;
  wrong: string;
}

const N_PER_G = 0.00981;

export const LESSONS: Record<StepId, Lesson> = {
  meeting: {
    step: "meeting",
    concept: "Requirements",
    body: "Sentences in your request become numbers a test can check. “Under 250 grams” the simulation can check. “Should look good” it cannot. Every requirement keeps its quote, so it stays clear who wanted it.",
    diagram: "requirements",
    formula: () => ({ left: "Sentence → number → test", right: "every requirement has a source" }),
    question: "Which requirement can the simulation check directly?",
    options: ["“Should look cool”", "“At least 10 minutes of flight time”", "“Lena likes blue”"],
    correct: 1,
    right: "Right. A number with a unit is something I can test. Coolness, not yet.",
    wrong: "Close. I can only test what has a number: the 10 minutes.",
  },
  teile: {
    step: "teile",
    concept: "Thrust-to-weight",
    body: "All motors together have to push much harder than the drone weighs. At 1 : 1 it barely hovers, with no reserve for wind or a maneuver. A rule of thumb for calm filming: at least 2 : 1.",
    diagram: "thrust",
    formula: (m) => ({
      left: m
        ? `T/W = ${fmtRatio(m.thrust_to_weight * m.weight_g * N_PER_G)} N ÷ ${fmtRatio(m.weight_g * N_PER_G)} N ≈ ${fmtRatio(m.thrust_to_weight)}`
        : "T/W = thrust ÷ weight",
      right: m ? `at ${fmtGram(m.weight_g)}` : "target ≥ 2",
    }),
    question: "The battery gets 50 g heavier and thrust stays the same. What happens to T/W?",
    options: ["it rises", "it stays the same", "it falls"],
    correct: 2,
    right: "Right. More weight at the same thrust means less reserve. That is what killed run 1.",
    wrong: "Not quite. Weight is on the bottom of the fraction, so the ratio falls.",
  },
  cad: {
    step: "cad",
    concept: "Parametric CAD",
    body: "The frame is not a painted model. It is a program with parameters: arm length, arm thickness, motor spacing. Change one number and CadQuery rebuilds the frame, including an STL for the printer.",
    diagram: "frame",
    formula: () => ({ left: "Frame = f(arm length, thickness, spacing)", right: "180 mm diagonal · 4 mm arms" }),
    question: "You want bigger propellers. What do you change in the model?",
    options: ["the arm length", "the color", "the battery"],
    correct: 0,
    right: "Right. Longer arms, more room for the props. One number, a new frame.",
    wrong: "The props need space between the motors, so the arms get longer.",
  },
  render: {
    step: "render",
    concept: "Rendering",
    body: "Blender turns the CAD model into a photo with real light and material. Before printing you can see whether the cables, battery and props fit, and you have a picture for the pitch deck.",
    diagram: "render",
    formula: () => ({ left: "Model + light + material = picture", right: "Cycles · 64 samples" }),
    question: "Why do we render before printing?",
    options: ["to save filament", "to check fit and look", "so the drone flies faster"],
    correct: 1,
    right: "Right. A render costs nothing. A bad print costs three hours.",
    wrong: "It does not make the drone fly better. But we see whether everything fits.",
  },
  simulation: {
    step: "simulation",
    concept: "Thrust-to-weight",
    body: "In MuJoCo the drone gets the real masses and the real thrust of the parts. Then it should climb to 1 m and hold in the wind. Too little reserve, and it drops, just like in real life.",
    diagram: "thrust",
    formula: (m) => ({
      left: m ? `T/W = ${fmtRatio(m.thrust_to_weight)} : 1` : "T/W = thrust ÷ weight",
      right: m ? `flight time ${fmtMin(m.flight_time_min)} min` : "target ≥ 2 : 1",
    }),
    question: "Run 1 had a T/W of 1.49 and dropped. What helps most?",
    options: ["a heavier battery", "a lighter battery", "painting the frame"],
    correct: 1,
    right: "Right. Less weight, more reserve. That is why I swapped the battery.",
    wrong: "Heavier makes it worse. The battery was the problem, so lighter.",
  },
  training: {
    step: "training",
    concept: "Reinforcement learning",
    body: "The drone learns by trying: calm hovering at the target gets a reward, wobble and a crash get a penalty. Isaac Lab lets 4096 drones practice at once, on a GPU at RunPod.",
    diagram: "reward",
    formula: () => ({ left: "Reward up = the policy flies better", right: "4096 environments in parallel" }),
    question: "Why do 4096 drones practice at once?",
    options: ["so it goes faster", "because one of them is scared", "for prettier videos"],
    correct: 0,
    right: "Right. 4096 times more experience per second. Drones are not scared. Neither am I.",
    wrong: "It is about speed: more attempts per second, learned faster.",
  },
  stueckliste: {
    step: "stueckliste",
    concept: "Budget and weight",
    body: "Every part costs money and grams. The battery is usually the heaviest and one of the most expensive parts, so it is worth optimizing first. The bill of materials shows both, per part.",
    diagram: "budget",
    formula: (m) => ({
      left: m ? `Total €${m.price_eur.toLocaleString("en-GB", { minimumFractionDigits: 2 })}` : "Total = Σ quantity × price",
      right: m ? `${fmtGram(m.weight_g)} total` : "budget €80",
    }),
    question: "Which part saved us the most weight?",
    options: ["the propellers", "the battery", "the screws"],
    correct: 1,
    right: "Right, the battery: 186 g down to 98 g. The rest was small change.",
    wrong: "The props weigh 2 g. The battery saved 88 g.",
  },
};
