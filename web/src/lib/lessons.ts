// "Erklär mir das": one concept per step, explained with the live numbers of the
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
    concept: "Anforderungen",
    body: "Aus Sätzen im Meeting werden prüfbare Zahlen. „Unter 250 Gramm“ kann die Simulation checken, „soll gut aussehen“ nicht. Jede Anforderung behält ihr Zitat, damit klar bleibt, wer sie wollte.",
    diagram: "requirements",
    formula: () => ({ left: "Satz → Zahl → Test", right: "jede Anforderung mit Quelle" }),
    question: "Welche Anforderung kann die Simulation direkt prüfen?",
    options: ["„Soll cool aussehen“", "„Mindestens 10 Minuten Flugzeit“", "„Lena mag Blau“"],
    correct: 1,
    right: "Genau. Eine Zahl mit Einheit kann ich testen. Coolness leider noch nicht.",
    wrong: "Fast. Testen kann ich nur, was eine Zahl hat: die 10 Minuten.",
  },
  teile: {
    step: "teile",
    concept: "Schub-Gewicht-Verhältnis",
    body: "Alle Motoren zusammen müssen deutlich mehr drücken, als die Drohne wiegt. Bei 1 : 1 schwebt sie gerade so, ohne Reserve für Wind oder Manöver. Faustregel für ruhiges Filmen: mindestens 2 : 1.",
    diagram: "thrust",
    formula: (m) => ({
      left: m
        ? `T/G = ${fmtRatio(m.thrust_to_weight * m.weight_g * N_PER_G)} N ÷ ${fmtRatio(m.weight_g * N_PER_G)} N ≈ ${fmtRatio(m.thrust_to_weight)}`
        : "T/G = Schub ÷ Gewicht",
      right: m ? `bei ${fmtGram(m.weight_g)}` : "Ziel ≥ 2",
    }),
    question: "Der Akku wird 50 g schwerer, der Schub bleibt gleich. Was passiert mit T/G?",
    options: ["steigt", "bleibt gleich", "sinkt"],
    correct: 2,
    right: "Richtig. Mehr Gewicht bei gleichem Schub, weniger Reserve. Genau das hat Lauf 1 gekillt.",
    wrong: "Nicht ganz. Das Gewicht steht unten im Bruch, also sinkt das Verhältnis.",
  },
  cad: {
    step: "cad",
    concept: "Parametrisches CAD",
    body: "Der Rahmen ist kein gemaltes Modell, sondern ein Programm mit Parametern: Armlänge, Armstärke, Motorabstand. Ändere eine Zahl, und CadQuery baut den Rahmen neu, inklusive STL für den Drucker.",
    diagram: "frame",
    formula: () => ({ left: "Rahmen = f(Armlänge, Stärke, Abstand)", right: "Diagonale 180 mm · Arme 4 mm" }),
    question: "Ihr wollt größere Propeller. Was änderst du im Modell?",
    options: ["die Armlänge", "die Farbe", "den Akku"],
    correct: 0,
    right: "Genau. Längere Arme, mehr Platz für die Props. Eine Zahl, neuer Rahmen.",
    wrong: "Die Props brauchen Platz zwischen den Motoren, also längere Arme.",
  },
  render: {
    step: "render",
    concept: "Rendern",
    body: "Blender rechnet aus dem CAD-Modell ein Foto mit echtem Licht und Material. So seht ihr vor dem Drucken, ob Kabel, Akku und Props zusammenpassen, und habt ein Bild fürs Pitch-Deck.",
    diagram: "render",
    formula: () => ({ left: "Modell + Licht + Material = Bild", right: "Cycles · 64 Samples" }),
    question: "Wozu rendern wir vor dem Drucken?",
    options: ["um Filament zu sparen", "um Passung und Look zu prüfen", "damit die Drohne schneller fliegt"],
    correct: 1,
    right: "Richtig. Ein Render kostet nichts, ein Fehldruck drei Stunden.",
    wrong: "Fliegen tut sie davon nicht besser. Aber wir sehen, ob alles passt.",
  },
  simulation: {
    step: "simulation",
    concept: "Schub-Gewicht-Verhältnis",
    body: "In MuJoCo bekommt die Drohne die echten Massen und den echten Schub der Teile. Dann soll sie auf 1 m steigen und im Wind stehen. Zu wenig Reserve, und sie sackt ab, genau wie in echt.",
    diagram: "thrust",
    formula: (m) => ({
      left: m ? `T/G = ${fmtRatio(m.thrust_to_weight)} : 1` : "T/G = Schub ÷ Gewicht",
      right: m ? `Flugzeit ${fmtMin(m.flight_time_min)} min` : "Ziel ≥ 2 : 1",
    }),
    question: "Lauf 1 hatte T/G 1,49 und sackte ab. Was hilft am meisten?",
    options: ["schwereren Akku nehmen", "leichteren Akku nehmen", "Rahmen lackieren"],
    correct: 1,
    right: "Richtig. Weniger Gewicht, mehr Reserve. Deshalb habe ich den Akku getauscht.",
    wrong: "Schwerer macht es schlimmer. Der Akku war das Problem, also leichter.",
  },
  training: {
    step: "training",
    concept: "Reinforcement Learning",
    body: "Die Drohne lernt durch Ausprobieren: Für ruhiges Schweben am Ziel gibt es Belohnung, für Wackeln und Absturz Abzug. Isaac Lab lässt 4096 Drohnen gleichzeitig üben, auf einer GPU bei RunPod.",
    diagram: "reward",
    formula: () => ({ left: "Belohnung ↑ = Policy fliegt besser", right: "4096 Umgebungen parallel" }),
    question: "Warum üben 4096 Drohnen gleichzeitig?",
    options: ["damit es schneller geht", "weil eine allein Angst hat", "für schönere Videos"],
    correct: 0,
    right: "Genau. 4096 mal mehr Erfahrung pro Sekunde. Angst haben Drohnen nicht. Ich auch nicht.",
    wrong: "Es geht um Tempo: mehr Versuche pro Sekunde, schneller gelernt.",
  },
  stueckliste: {
    step: "stueckliste",
    concept: "Budget und Gewicht",
    body: "Jedes Teil kostet Geld und Gramm. Der Akku ist meist das schwerste und eines der teuersten Teile, deshalb lohnt es sich, ihn zuerst zu optimieren. Die Stückliste zeigt beides pro Teil.",
    diagram: "budget",
    formula: (m) => ({
      left: m ? `Summe ${m.price_eur.toLocaleString("de-DE", { minimumFractionDigits: 2 })} €` : "Summe = Σ Menge × Preis",
      right: m ? `${fmtGram(m.weight_g)} gesamt` : "Budget 80 €",
    }),
    question: "Welches Teil hat bei uns am meisten Gewicht gespart?",
    options: ["die Propeller", "der Akku", "die Schrauben"],
    correct: 1,
    right: "Klar, der Akku: 186 g auf 98 g. Der Rest war Kleinkram.",
    wrong: "Die Props wiegen 2 g. Der Akku hat 88 g gespart.",
  },
};
