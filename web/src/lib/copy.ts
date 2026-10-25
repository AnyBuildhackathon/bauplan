// Older recordings and a few backend details still carry German phrases.
// The stage shows the English form. Strings that are already English pass through.

const PHRASES: [RegExp, string][] = [
  [/Bauplan/g, "AnyBuild"],
  [/(\d+) Änderungen/g, "$1 changes"],
  [/(\d+) Änderung/g, "$1 change"],
  [/(\d+) Vorgaben/g, "$1 requirements"],
  [/Schub\/Gewicht /g, "Thrust/weight "],
  [/Flugzeit /g, "Flight time "],
  [/Gewicht /g, "Weight "],
  [/Preis /g, "Price "],
  [/Flugregler: /g, "Flight controller: "],
  [/Akku: /g, "Battery: "],
  [/Rahmen: /g, "Frame: "],
  [/„/g, '"'],
  [/“/g, '"'],
  [/”/g, '"'],
];

const LABELS: Record<string, string> = {
  Gewicht: "Weight",
  Flugzeit: "Flight time",
  Preis: "Price",
  "Schub/Gewicht": "Thrust/weight",
  Akku: "Battery",
  Flugregler: "Flight controller",
  Rahmen: "Frame",
  Motor: "Motor",
  Propeller: "Propeller",
  Minuten: "min",
};

export function enText(text: string): string {
  let out = text;
  for (const [pattern, replacement] of PHRASES) out = out.replace(pattern, replacement);
  return out;
}

export function enLabel(label: string): string {
  return LABELS[label] ?? enText(label);
}
