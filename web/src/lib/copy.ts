// Jamie still emits a few German phrases from the module this UI does not own.
// The stage shows the English form. Strings that are already English pass through.

const PHRASES: [RegExp, string][] = [
  [/Aus Bauplan, Preis ist eine Stichprobe/g, "From AnyBuild, price is a sample"],
  [/Bauplan/g, "AnyBuild"],
  [/AnyBuild v(\d+) aus /g, "AnyBuild v$1 from "],
  [/lokale Outbox/g, "local outbox"],
  [/lokal, Jamie nicht erreichbar/g, "local, Jamie unreachable"],
  [/Hardware-Anforderungen/g, "Hardware requirements"],
  [/Drohnen-Review/g, "Drone review"],
  [/(\d+) Änderungen/g, "$1 changes"],
  [/(\d+) Änderung/g, "$1 change"],
  [/(\d+) Beschwerden/g, "$1 complaints"],
  [/(\d+) Beschwerde/g, "$1 complaint"],
  [/(\d+) Vorgaben/g, "$1 requirements"],
  [/1 Treffer für/g, "1 hit for"],
  [/(\d+) Treffer für/g, "$1 hits for"],
  [/Vorlagen /g, "Templates "],
  [/Vorlage „/g, 'Template "'],
  [/Notiz an /g, "Note on "],
  [/Differenz zu /g, "diff from "],
  [/(\d+) Aufgaben für/g, "$1 tasks for"],
  [/(\d+) Aufgabe für/g, "$1 task for"],
  [/(\d+) alte Aufgaben geschlossen/g, "$1 old tasks closed"],
  [/(\d+) neue Aufgaben, (\d+) bleiben/g, "$1 new tasks, $2 unchanged"],
  [/ ist zu Ende/g, " ended"],
  [/Bestellen: /g, "Order: "],
  [/Drucken: /g, "Print: "],
  [/Schub\/Gewicht /g, "Thrust/weight "],
  [/Flugzeit /g, "Flight time "],
  [/Gewicht /g, "Weight "],
  [/Preis /g, "Price "],
  [/Flugregler: /g, "Flight controller: "],
  [/Akku: /g, "Battery: "],
  [/Rahmen: /g, "Frame: "],
  [/ gemeint: /g, " means: "],
  [/Übernommen: nichts/g, "Accepted: nothing"],
  [/Übernommen: /g, "Accepted: "],
  [/„/g, '"'],
  [/“/g, '"'],
  [/”/g, '"'],
  [/(drohne(?:-v\d+)?) an /g, "$1 on "],
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
