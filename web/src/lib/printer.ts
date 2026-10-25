// "I have a 3D printer": the user's printer model and filaments. The choice lives in this
// browser (localStorage) and goes to the backend with POST /api/settings {printer}, again
// whenever the backend (re)connects, so a restarted backend still knows it. The profiles
// (bed, nozzle, enclosure, printable materials, the maker's spec page) come from the backend's
// store with GET /api/settings. Without a printer the app behaves as before.
import { useEffect } from "react";
import { create } from "zustand";
import { useSource } from "../events/source";
import type { PrinterProfile, UserPrinter } from "../events/types";
import { apiFetch } from "./api";

const KEY = "anybuild.printer";

export interface PrinterChoice {
  model: string;
  filaments: string[];
}

export interface FilamentInfo {
  id: string;
  name: string;
  eur_per_kg: number;
  needs_enclosure: boolean;
}

interface PrinterState {
  /** What this browser saved; null without a printer. */
  choice: PrinterChoice | null;
  /** The backend's answer for the current choice: the profile and what it prints from the filaments. */
  printer: UserPrinter | null;
  printers: PrinterProfile[];
  filaments: FilamentInfo[];
  error: string | null;
  /** Saves and sends a choice; null switches the printer off. */
  choose: (choice: PrinterChoice | null) => Promise<void>;
  load: () => Promise<void>;
}

function saved(): PrinterChoice | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as PrinterChoice;
    return typeof value?.model === "string" && Array.isArray(value.filaments) ? value : null;
  } catch {
    return null;
  }
}

function save(choice: PrinterChoice | null) {
  try {
    if (choice) localStorage.setItem(KEY, JSON.stringify(choice));
    else localStorage.removeItem(KEY);
  } catch {
    // Private windows may refuse storage; the backend still has the choice for this session.
  }
}

interface SettingsBody {
  printer: UserPrinter | null;
  printer_catalog: { printers: PrinterProfile[]; filaments: FilamentInfo[] };
}

async function post(choice: PrinterChoice | null): Promise<SettingsBody> {
  const res = await apiFetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ printer: choice }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as SettingsBody;
}

export const usePrinter = create<PrinterState>((set, get) => ({
  choice: saved(),
  printer: null,
  printers: [],
  filaments: [],
  error: null,
  choose: async (choice) => {
    save(choice);
    set({ choice, error: null });
    try {
      const body = await post(choice);
      set({ printer: body.printer, printers: body.printer_catalog.printers, filaments: body.printer_catalog.filaments });
    } catch (err) {
      set({ error: `Printer not sent to the backend (${err instanceof Error ? err.message : "error"}).` });
    }
  },
  load: async () => {
    try {
      // This browser's saved printer goes to the backend; without one, show what the backend has.
      const { choice } = get();
      const body = choice
        ? await post(choice)
        : ((await (await apiFetch("/api/settings")).json()) as SettingsBody);
      set({ printer: body.printer, printers: body.printer_catalog?.printers ?? [], filaments: body.printer_catalog?.filaments ?? [], error: null });
    } catch {
      set({ error: "The printer list needs the live backend." });
    }
  },
}));

/** Sends the saved printer whenever the backend connects. Mounted once in App. */
export function usePrinterSync() {
  const backend = useSource((s) => s.backend);
  useEffect(() => {
    if (backend) void usePrinter.getState().load();
  }, [backend]);
}
