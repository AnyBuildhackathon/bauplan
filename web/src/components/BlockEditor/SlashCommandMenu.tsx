// Adapted from core-oss (github.com/10xapp/core-oss, Apache-2.0),
// core-web/src/components/BlockEditor/SlashCommandMenu.tsx. Modified: Bevel
// tokens and German labels.
import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'motion/react';
import { BLOCK_TYPE_OPTIONS, type BlockType } from './types';

interface SlashCommandMenuProps {
  position: { top: number; left: number };
  onSelect: (type: BlockType) => void;
  onClose: () => void;
}

export default function SlashCommandMenu({ position, onSelect, onClose }: SlashCommandMenuProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [query, setQuery] = useState('');
  const menuRef = useRef<HTMLDivElement>(null);

  const filtered = BLOCK_TYPE_OPTIONS.filter(
    opt => opt.label.toLowerCase().includes(query.toLowerCase()) ||
           opt.description.toLowerCase().includes(query.toLowerCase())
  );

  // Reset selection when filter changes
  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        e.stopPropagation();
        setSelectedIndex(prev => (prev + 1) % Math.max(filtered.length, 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        e.stopPropagation();
        setSelectedIndex(prev => (prev - 1 + filtered.length) % Math.max(filtered.length, 1));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        e.stopPropagation();
        if (filtered.length > 0) {
          onSelect(filtered[selectedIndex].type);
        }
      } else if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      } else if (e.key === 'Backspace') {
        if (query.length === 0) {
          onClose();
        } else {
          setQuery(prev => prev.slice(0, -1));
        }
      } else if (e.key.length === 1 && !e.metaKey && !e.ctrlKey) {
        setQuery(prev => prev + e.key);
      }
    };

    document.addEventListener('keydown', handleKeyDown, true);
    return () => document.removeEventListener('keydown', handleKeyDown, true);
  }, [filtered, selectedIndex, query, onSelect, onClose]);

  // Click outside
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [onClose]);

  // Ensure menu doesn't go off screen
  const adjustedTop = Math.min(position.top, window.innerHeight - 400);

  return createPortal(
    <AnimatePresence>
      <motion.div
        ref={menuRef}
        initial={{ opacity: 0, y: -4 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={{ duration: 0.12 }}
        className="fixed bg-card rounded-2xl shadow-[var(--shadow-float)] py-1 z-[9999] w-[280px] max-h-[360px] overflow-y-auto"
        style={{ top: adjustedTop, left: position.left }}
      >
        <div className="px-3 py-2 text-xs font-medium text-faint uppercase tracking-wider">
          Blöcke
        </div>
        {filtered.length === 0 ? (
          <div className="px-3 py-3 text-sm text-faint">Keine Treffer</div>
        ) : (
          filtered.map((option, i) => (
            <button
              key={option.type}
              onClick={() => onSelect(option.type)}
              onMouseEnter={() => setSelectedIndex(i)}
              className={`w-full flex items-center gap-3 px-3 py-2 text-left transition-colors ${
                i === selectedIndex ? 'bg-tile' : 'hover:bg-tile'
              }`}
            >
              <span className="w-8 h-8 flex items-center justify-center rounded bg-tile text-muted text-xs font-medium flex-shrink-0">
                {option.icon}
              </span>
              <div>
                <div className="text-sm font-medium text-ink">{option.label}</div>
                <div className="text-xs text-faint">{option.description}</div>
              </div>
            </button>
          ))
        )}
      </motion.div>
    </AnimatePresence>,
    document.body
  );
}
