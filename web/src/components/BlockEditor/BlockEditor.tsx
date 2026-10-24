// Adapted from core-oss (github.com/10xapp/core-oss, Apache-2.0),
// core-web/src/components/BlockEditor/BlockEditor.tsx. Modified: Bevel tokens,
// tighter padding for the logbook card.
import { useState, useCallback, useEffect, useRef } from 'react';
import Block from './Block';
import SlashCommandMenu from './SlashCommandMenu';
import { createBlock, parseBlocksFromContent, serializeBlocks, type Block as BlockData, type BlockType } from './types';

interface BlockEditorProps {
  content: string;
  onChange: (content: string) => void;
  placeholder?: string;
}

export default function BlockEditor({ content, onChange }: BlockEditorProps) {
  const [blocks, setBlocks] = useState<BlockData[]>(() => parseBlocksFromContent(content));
  const [focusedBlockId, setFocusedBlockId] = useState<string | null>(null);
  const [slashMenu, setSlashMenu] = useState<{ blockId: string; position: { top: number; left: number } } | null>(null);
  const [draggedIndex, setDraggedIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const contentRef = useRef(content);
  const isInternalChange = useRef(false);

  // Emit changes
  const emitChange = useCallback((newBlocks: BlockData[]) => {
    const serialized = serializeBlocks(newBlocks);
    contentRef.current = serialized;
    isInternalChange.current = true;
    onChange(serialized);
  }, [onChange]);

  // Sync from external content changes (e.g., switching notes)
  useEffect(() => {
    if (isInternalChange.current) {
      isInternalChange.current = false;
      return;
    }
    if (content !== contentRef.current) {
      contentRef.current = content;
      const parsed = parseBlocksFromContent(content);
      setBlocks(parsed);
      setFocusedBlockId(null);
      setSlashMenu(null);
    }
  }, [content]);

  const updateBlock = useCallback((id: string, newContent: string) => {
    setBlocks(prev => {
      const updated = prev.map(b => b.id === id ? { ...b, content: newContent } : b);
      emitChange(updated);
      return updated;
    });
  }, [emitChange]);

  const addBlockAfter = useCallback((id: string) => {
    const newBlock = createBlock();
    setBlocks(prev => {
      const index = prev.findIndex(b => b.id === id);
      const updated = [...prev];
      updated.splice(index + 1, 0, newBlock);
      emitChange(updated);
      return updated;
    });
    setFocusedBlockId(newBlock.id);
    setSlashMenu(null);
  }, [emitChange]);

  const deleteBlock = useCallback((id: string) => {
    setBlocks(prev => {
      if (prev.length <= 1) return prev; // Keep at least one block
      const index = prev.findIndex(b => b.id === id);
      const updated = prev.filter(b => b.id !== id);
      emitChange(updated);
      // Focus previous block
      const focusIndex = Math.max(0, index - 1);
      setFocusedBlockId(updated[focusIndex]?.id || null);
      return updated;
    });
    setSlashMenu(null);
  }, [emitChange]);

  const changeBlockType = useCallback((id: string, type: BlockType) => {
    setBlocks(prev => {
      const updated = prev.map(b => b.id === id ? { ...b, type, content: type === 'divider' ? '' : b.content } : b);
      emitChange(updated);
      return updated;
    });
  }, [emitChange]);

  const focusPreviousBlock = useCallback((id: string) => {
    setBlocks(prev => {
      const index = prev.findIndex(b => b.id === id);
      if (index > 0) {
        setFocusedBlockId(prev[index - 1].id);
      }
      return prev;
    });
  }, []);

  const focusNextBlock = useCallback((id: string) => {
    setBlocks(prev => {
      const index = prev.findIndex(b => b.id === id);
      if (index < prev.length - 1) {
        setFocusedBlockId(prev[index + 1].id);
      }
      return prev;
    });
  }, []);

  const handleSlashCommand = useCallback((blockId: string, rect: DOMRect) => {
    setSlashMenu({
      blockId,
      position: { top: rect.bottom + 4, left: rect.left },
    });
  }, []);

  const handleSlashSelect = useCallback((type: BlockType) => {
    if (!slashMenu) return;

    // Clear the "/" from the block content
    updateBlock(slashMenu.blockId, '');
    changeBlockType(slashMenu.blockId, type);

    // If divider, add a new block after it
    if (type === 'divider') {
      addBlockAfter(slashMenu.blockId);
    } else {
      setFocusedBlockId(slashMenu.blockId);
    }

    setSlashMenu(null);
  }, [slashMenu, updateBlock, changeBlockType, addBlockAfter]);

  // Drag and drop
  const handleDragStart = useCallback((index: number) => {
    setDraggedIndex(index);
  }, []);

  const handleDragOver = useCallback((index: number) => {
    setDragOverIndex(index);
  }, []);

  const handleDragEnd = useCallback(() => {
    if (draggedIndex !== null && dragOverIndex !== null && draggedIndex !== dragOverIndex) {
      setBlocks(prev => {
        const updated = [...prev];
        const [moved] = updated.splice(draggedIndex, 1);
        updated.splice(dragOverIndex, 0, moved);
        emitChange(updated);
        return updated;
      });
    }
    setDraggedIndex(null);
    setDragOverIndex(null);
  }, [draggedIndex, dragOverIndex, emitChange]);

  // Click on empty space below blocks to focus last block or create new one
  const handleContainerClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) {
      const lastBlock = blocks[blocks.length - 1];
      if (lastBlock && lastBlock.content === '' && lastBlock.type === 'paragraph') {
        setFocusedBlockId(lastBlock.id);
      } else {
        const newBlock = createBlock();
        setBlocks(prev => {
          const updated = [...prev, newBlock];
          emitChange(updated);
          return updated;
        });
        setFocusedBlockId(newBlock.id);
      }
    }
  }, [blocks, emitChange]);

  return (
    <div className="flex flex-col h-full">
      <div
        className="scroll-soft flex-1 overflow-y-auto pl-10 pr-4 py-2 cursor-text"
        onClick={handleContainerClick}
      >
        <div className="space-y-1">
          {blocks.map((block, index) => (
            <Block
              key={block.id}
              block={block}
              index={index}
              isFocused={focusedBlockId === block.id}
              isOnly={blocks.length === 1}
              onUpdate={updateBlock}
              onFocus={setFocusedBlockId}
              onAddAfter={addBlockAfter}
              onDelete={deleteBlock}
              onChangeType={changeBlockType}
              onMoveUp={focusPreviousBlock}
              onMoveDown={focusNextBlock}
              onSlashCommand={handleSlashCommand}
              onDragStart={handleDragStart}
              onDragOver={handleDragOver}
              onDragEnd={handleDragEnd}
              isDragOver={dragOverIndex === index && draggedIndex !== null && draggedIndex !== index}
            />
          ))}
        </div>
      </div>

      {/* Slash command menu */}
      {slashMenu && (
        <SlashCommandMenu
          position={slashMenu.position}
          onSelect={handleSlashSelect}
          onClose={() => setSlashMenu(null)}
        />
      )}
    </div>
  );
}
