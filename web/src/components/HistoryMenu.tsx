// The chat history on the icon rail: every saved conversation with its title and time.
// Clicking one reopens it on the bench with its messages and the product it built.
import { useEffect, useRef, useState } from "react";
import { History } from "lucide-react";
import { useSource } from "../events/source";
import { useUi } from "../lib/ui";
import { loadHistory, whenText, type SavedChat } from "../lib/history";

export function HistoryMenu() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<SavedChat[] | null>(null);
  const [current, setCurrent] = useState("");
  const [opening, setOpening] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const openChat = useSource((s) => s.openChat);
  const setView = useUi((s) => s.setView);
  const resetUi = useUi((s) => s.resetUi);

  useEffect(() => {
    if (!open) return;
    let live = true;
    void loadHistory().then((h) => {
      if (!live) return;
      setItems(h.items);
      setCurrent(h.current);
    });
    const close = (e: PointerEvent) => {
      if (e.isTrusted && !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const escape = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", escape);
    return () => {
      live = false;
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", escape);
    };
  }, [open]);

  const pick = async (chat: SavedChat) => {
    if (chat.id !== current) {
      setOpening(chat.id);
      const ok = await openChat(chat.id);
      setOpening(null);
      if (!ok) return;
      resetUi();
    }
    setView("werkbank");
    setOpen(false);
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        title="Chat history"
        aria-label="Chat history"
        aria-expanded={open}
        data-target="nav:history"
        className={`flex h-11 w-11 items-center justify-center rounded-[12px] transition ${
          open ? "bg-track text-ink" : "text-ink-2 hover:bg-tile hover:text-ink"
        }`}
      >
        <History className="h-5 w-5" strokeWidth={1.8} />
      </button>
      {open && (
        <div className="absolute top-0 left-[52px] z-[90] flex max-h-[min(560px,calc(100vh-96px))] w-[340px] animate-rise flex-col rounded-[20px] bg-card p-2 shadow-[var(--shadow-float)]">
          <h3 className="eyebrow px-3 pt-2 pb-1.5">Chats</h3>
          <ul className="scroll-soft min-h-0 flex-1 overflow-y-auto">
            {items === null && <li className="px-3 py-2 text-[14px] text-muted">Loading …</li>}
            {items?.length === 0 && <li className="px-3 py-2 text-[14px] text-muted">No saved chats yet. Every chat you start lands here.</li>}
            {items?.map((chat) => {
              const isCurrent = chat.id === current;
              const meta = [whenText(chat.updated_at), chat.product, chat.versions ? `${chat.versions} ${chat.versions === 1 ? "version" : "versions"}` : ""].filter(Boolean);
              return (
                <li key={chat.id}>
                  <button
                    type="button"
                    onClick={() => void pick(chat)}
                    disabled={opening !== null}
                    aria-current={isCurrent ? "true" : undefined}
                    className={`flex w-full items-start gap-2 rounded-[12px] px-3 py-2 text-left transition disabled:cursor-wait ${
                      isCurrent ? "bg-tile" : "hover:bg-tile"
                    }`}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[14px] font-semibold text-ink">{chat.title}</span>
                      <span className="num block truncate text-[12px] text-muted">{meta.join(" · ")}</span>
                    </span>
                    {isCurrent && <span className="mt-0.5 shrink-0 text-[12px] font-semibold text-ink-2">Open</span>}
                    {opening === chat.id && <span className="mt-0.5 shrink-0 text-[12px] font-semibold text-muted">Opening …</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
