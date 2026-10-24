// Adapted from core-oss (github.com/10xapp/core-oss, Apache-2.0),
// core-web/src/components/BlockEditor/Block.tsx. Modified: Bevel tokens, German
// placeholders, larger type for the projector.
import { useRef, useEffect, useCallback } from 'react';
import type { Block as BlockData, BlockType } from './types';
import { sanitizeStrictHtml } from '../../utils/sanitizeHtml';

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

interface BlockProps {
  block: BlockData;
  index: number;
  isFocused: boolean;
  isOnly: boolean;
  onUpdate: (id: string, content: string) => void;
  onFocus: (id: string) => void;
  onAddAfter: (id: string) => void;
  onDelete: (id: string) => void;
  onChangeType: (id: string, type: BlockType) => void;
  onMoveUp: (id: string) => void;
  onMoveDown: (id: string) => void;
  onSlashCommand: (id: string, rect: DOMRect) => void;
  onDragStart: (index: number) => void;
  onDragOver: (index: number) => void;
  onDragEnd: () => void;
  isDragOver: boolean;
}

export default function Block({
  block,
  index,
  isFocused,
  isOnly,
  onUpdate,
  onFocus,
  onAddAfter,
  onDelete,
  onMoveUp,
  onMoveDown,
  onSlashCommand,
  onDragStart,
  onDragOver,
  onDragEnd,
  isDragOver,
}: BlockProps) {
  const ref = useRef<HTMLDivElement>(null);

  // Focus the contenteditable when this block becomes focused
  useEffect(() => {
    if (isFocused && ref.current && document.activeElement !== ref.current) {
      ref.current.focus();
      // Move cursor to end
      const sel = window.getSelection();
      if (sel && ref.current.childNodes.length > 0) {
        sel.selectAllChildren(ref.current);
        sel.collapseToEnd();
      }
    }
  }, [isFocused]);

  const handleInput = useCallback(() => {
    if (ref.current) {
      const html = ref.current.innerHTML;
      // Check if user just typed /
      const text = ref.current.textContent || '';
      if (text === '/') {
        const rect = ref.current.getBoundingClientRect();
        onSlashCommand(block.id, rect);
        return;
      }
      onUpdate(block.id, html);
    }
  }, [block.id, onUpdate, onSlashCommand]);

  const handlePaste = useCallback((e: React.ClipboardEvent<HTMLDivElement>) => {
    e.preventDefault();
    const html = e.clipboardData.getData('text/html');
    const text = e.clipboardData.getData('text/plain');
    const sanitized = html
      ? sanitizeStrictHtml(html)
      : escapeHtml(text).replace(/\n/g, '<br>');
    document.execCommand('insertHTML', false, sanitized);
    handleInput();
  }, [handleInput]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    const el = ref.current;
    if (!el) return;

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onAddAfter(block.id);
      return;
    }

    if (e.key === 'Backspace') {
      const text = el.textContent || '';
      if (text === '' && !isOnly) {
        e.preventDefault();
        onDelete(block.id);
        return;
      }
      // If cursor is at beginning, merge with previous block
      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0) {
        const range = sel.getRangeAt(0);
        if (range.startOffset === 0 && range.collapsed) {
          const firstNode = el.firstChild;
          if (!firstNode || range.startContainer === el || range.startContainer === firstNode) {
            if (text === '' || range.startOffset === 0) {
              e.preventDefault();
              onDelete(block.id);
              return;
            }
          }
        }
      }
    }

    if (e.key === 'ArrowUp') {
      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0) {
        const range = sel.getRangeAt(0);
        if (range.collapsed && range.startOffset === 0) {
          e.preventDefault();
          onMoveUp(block.id);
        }
      }
    }

    if (e.key === 'ArrowDown') {
      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0) {
        const range = sel.getRangeAt(0);
        const text = el.textContent || '';
        if (range.collapsed && range.startOffset === text.length) {
          e.preventDefault();
          onMoveDown(block.id);
        }
      }
    }

    // Inline formatting shortcuts
    if (e.metaKey || e.ctrlKey) {
      if (e.key === 'b') {
        e.preventDefault();
        document.execCommand('bold');
        handleInput();
      } else if (e.key === 'i') {
        e.preventDefault();
        document.execCommand('italic');
        handleInput();
      } else if (e.key === 'u') {
        e.preventDefault();
        document.execCommand('underline');
        handleInput();
      }
    }
  }, [block.id, isOnly, onAddAfter, onDelete, onMoveUp, onMoveDown, handleInput]);

  // Sync content from props when block content changes externally
  useEffect(() => {
    const sanitizedContent = sanitizeStrictHtml(block.content);
    if (ref.current && ref.current.innerHTML !== sanitizedContent) {
      ref.current.innerHTML = sanitizedContent;
    }
  }, [block.content]);

  if (block.type === 'divider') {
    return (
      <div
        className={`group relative py-2 ${isDragOver ? 'border-t-2 border-agent' : ''}`}
        onClick={() => onFocus(block.id)}
        onDragOver={(e) => { e.preventDefault(); onDragOver(index); }}
      >
        {/* Drag handle */}
        <div
          className="absolute -left-8 top-1/2 -translate-y-1/2 w-6 h-6 flex items-center justify-center cursor-grab opacity-0 group-hover:opacity-100 transition-opacity text-faint hover:text-ink"
          draggable
          onDragStart={() => onDragStart(index)}
          onDragEnd={onDragEnd}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
            <circle cx="4" cy="3" r="1.5" /><circle cx="10" cy="3" r="1.5" />
            <circle cx="4" cy="7" r="1.5" /><circle cx="10" cy="7" r="1.5" />
            <circle cx="4" cy="11" r="1.5" /><circle cx="10" cy="11" r="1.5" />
          </svg>
        </div>
        <hr className="border-line" />
      </div>
    );
  }

  const typeStyles: Record<string, string> = {
    paragraph: 'text-[16px] leading-relaxed',
    heading1: 'text-[26px] font-extrabold tracking-[-0.02em] leading-tight',
    heading2: 'text-[20px] font-bold leading-tight pt-2',
    heading3: 'text-[17px] font-bold leading-snug',
    bulletList: 'text-[16px] leading-relaxed pl-6',
    numberedList: 'text-[16px] leading-relaxed pl-6',
    code: 'font-mono text-sm bg-tile rounded-lg p-4 leading-relaxed',
    quote: 'text-[16px] leading-relaxed border-l-[3px] border-jamie pl-4 text-ink-2',
  };

  const listMarker = block.type === 'bulletList'
    ? <span className="absolute -left-0 top-0 select-none text-faint" style={{ width: '1.5rem', textAlign: 'center' }}>•</span>
    : block.type === 'numberedList'
    ? <span className="absolute -left-0 top-0 select-none text-faint" style={{ width: '1.5rem', textAlign: 'center' }}>{index + 1}.</span>
    : null;

  const showPlaceholder = isFocused && (block.content === '' || block.content === '<br>');

  return (
    <div
      className={`group relative ${isDragOver ? 'border-t-2 border-agent' : ''}`}
      onDragOver={(e) => { e.preventDefault(); onDragOver(index); }}
    >
      {/* Drag handle */}
      <div
        className="absolute -left-8 top-1 w-6 h-6 flex items-center justify-center cursor-grab opacity-0 group-hover:opacity-100 transition-opacity text-faint hover:text-ink"
        draggable
        onDragStart={() => onDragStart(index)}
        onDragEnd={onDragEnd}
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
          <circle cx="4" cy="3" r="1.5" /><circle cx="10" cy="3" r="1.5" />
          <circle cx="4" cy="7" r="1.5" /><circle cx="10" cy="7" r="1.5" />
          <circle cx="4" cy="11" r="1.5" /><circle cx="10" cy="11" r="1.5" />
        </svg>
      </div>

      {/* List marker */}
      {listMarker && <div className="relative">{listMarker}</div>}

      {/* Content */}
      <div className="relative">
        {showPlaceholder && (
          <span className="absolute top-0 left-0 pointer-events-none select-none text-faint">
            {isOnly ? "Type '/' for blocks …" : 'Write something …'}
          </span>
        )}
        <div
          ref={ref}
          contentEditable
          suppressContentEditableWarning
          onInput={handleInput}
          onPaste={handlePaste}
          onKeyDown={handleKeyDown}
          onFocus={() => onFocus(block.id)}
          className={`outline-none ${typeStyles[block.type] || typeStyles.paragraph}`}
          data-block-id={block.id}
        />
      </div>
    </div>
  );
}
