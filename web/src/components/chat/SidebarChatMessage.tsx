// Adapted from core-oss (github.com/10xapp/core-oss, Apache-2.0),
// core-web/src/components/SidebarChat/SidebarChatMessage.tsx. Modified: Bevel
// styling, Bolzen's head on agent messages, a "gesprochen" hint on user messages,
// and the word-by-word reveal from core-oss SidebarChat moved into the message.
import { memo, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
import { Check, Copy } from "lucide-react";
import type { MascotState } from "../../events/types";
import { MascotHead } from "../mascot/Mascot";

interface ChatMessageProps {
  role: "user" | "agent";
  content: string;
  /** Reveal word by word (true only for messages that just arrived). */
  animate: boolean;
  mascot: MascotState;
  onRevealProgress?: () => void;
}

const markdown: Components = {
  p({ children }) {
    return <p className="mb-2 last:mb-0">{children}</p>;
  },
  strong({ children }) {
    return <strong className="font-bold text-ink">{children}</strong>;
  },
  ul({ children }) {
    return <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>;
  },
  a({ href, children }) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className="font-semibold text-link hover:underline">
        {children}
      </a>
    );
  },
};

const splitIntoSegments = (input: string): string[] => input.match(/\s+|[^\s]+/g) ?? [];

/** core-oss reveal timing: one tick every 35 ms, more words per tick when far behind. */
function useWordReveal(text: string, animate: boolean, onProgress?: () => void): { shown: string; streaming: boolean } {
  const [count, setCount] = useState(() => (animate ? 0 : Number.POSITIVE_INFINITY));
  const segments = useMemo(() => splitIntoSegments(text), [text]);
  const total = segments.length;
  useEffect(() => {
    if (count >= total) return;
    const id = setTimeout(() => {
      const behind = total - count;
      const step = behind > 60 ? 4 : behind > 30 ? 2 : 1;
      let next = count;
      let words = 0;
      while (next < total && words < step) {
        if (segments[next].trim()) words++;
        next++;
      }
      setCount(next);
      onProgress?.();
    }, 35);
    return () => clearTimeout(id);
  }, [count, total, segments, onProgress]);
  if (count >= total) return { shown: text, streaming: false };
  return { shown: segments.slice(0, count).join(""), streaming: true };
}

function UserMessage({ content }: { content: string }) {
  const isShort = content.length <= 48 && !content.includes("\n");
  return (
    <div className="flex flex-col items-end py-1.5 pl-10">
      <div className={`bg-tile px-4 py-2.5 ${isShort ? "rounded-full" : "rounded-[20px] rounded-br-md"}`}>
        <p className="text-[15px] leading-snug whitespace-pre-wrap text-ink">{content}</p>
      </div>
    </div>
  );
}

function AssistantMessage({ content, animate, mascot, onRevealProgress }: Omit<ChatMessageProps, "role">) {
  const [copied, setCopied] = useState(false);
  const { shown, streaming } = useWordReveal(content, animate, onRevealProgress);

  const handleCopyMessage = async () => {
    try {
      await navigator.clipboard.writeText(content.replace(/\*\*/g, ""));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard may be blocked outside secure contexts; nothing to recover.
    }
  };

  return (
    <div className="group flex items-start gap-2.5 py-1.5">
      <MascotHead size={24} state={mascot} className="mt-0.5 self-start" />
      <div className="min-w-0 flex-1">
        <div className="text-[15px] leading-[1.5] text-ink-2">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdown}>
            {shown}
          </ReactMarkdown>
          {streaming && <span className="ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 animate-pulse rounded-sm bg-agent" />}
        </div>
        {!streaming && (
          <div className="mt-0.5 opacity-0 transition-opacity group-hover:opacity-100">
            <button
              onClick={handleCopyMessage}
              className="rounded-md p-1 text-faint transition-colors hover:bg-tile hover:text-ink-2"
              title="Kopieren"
            >
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function SidebarChatMessage({ role, ...rest }: ChatMessageProps) {
  if (role === "user") return <UserMessage content={rest.content} />;
  return <AssistantMessage {...rest} />;
}

export default memo(SidebarChatMessage);
