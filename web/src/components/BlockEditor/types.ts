// Adapted from core-oss (github.com/10xapp/core-oss, Apache-2.0),
// core-web/src/components/BlockEditor/types.ts. Modified: German block labels and
// a Markdown serializer for the logbook export.
export type BlockType =
  | 'paragraph'
  | 'heading1'
  | 'heading2'
  | 'heading3'
  | 'bulletList'
  | 'numberedList'
  | 'code'
  | 'quote'
  | 'divider';

export interface Block {
  id: string;
  type: BlockType;
  content: string;
}

export interface BlockTypeOption {
  type: BlockType;
  label: string;
  description: string;
  icon: string;
}

export const BLOCK_TYPE_OPTIONS: BlockTypeOption[] = [
  { type: 'paragraph', label: 'Text', description: 'Plain text', icon: 'Aa' },
  { type: 'heading1', label: 'Heading 1', description: 'Large heading', icon: 'H1' },
  { type: 'heading2', label: 'Heading 2', description: 'Medium heading', icon: 'H2' },
  { type: 'heading3', label: 'Heading 3', description: 'Small heading', icon: 'H3' },
  { type: 'bulletList', label: 'List', description: 'Bullet list', icon: '•' },
  { type: 'numberedList', label: 'Numbered', description: 'Numbered list', icon: '1.' },
  { type: 'code', label: 'Code', description: 'Code block', icon: '</>' },
  { type: 'quote', label: 'Quote', description: 'Quote from the meeting', icon: '"' },
  { type: 'divider', label: 'Divider', description: 'Horizontal line', icon: '-' },
];

let blockCounter = 0;

export function generateBlockId(): string {
  return `block-${Date.now()}-${++blockCounter}`;
}

export function createBlock(type: BlockType = 'paragraph', content = ''): Block {
  return { id: generateBlockId(), type, content };
}

export function parseBlocksFromContent(content: string): Block[] {
  if (!content || content.trim() === '') {
    return [createBlock()];
  }

  try {
    const parsed = JSON.parse(content);
    if (Array.isArray(parsed) && parsed.length > 0) {
      return parsed;
    }
  } catch {
    // Legacy HTML content — wrap in a single paragraph block
  }

  return [createBlock('paragraph', content)];
}

export function serializeBlocks(blocks: Block[]): string {
  return JSON.stringify(blocks);
}

function htmlToMarkdownInline(html: string): string {
  return html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<(b|strong)>(.*?)<\/\1>/gi, '**$2**')
    .replace(/<(i|em)>(.*?)<\/\1>/gi, '_$2_')
    .replace(/<a [^>]*href="([^"]*)"[^>]*>(.*?)<\/a>/gi, '[$2]($1)')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}

/** Serializes blocks to Markdown for the logbook export. */
export function blocksToMarkdown(blocks: Block[]): string {
  let n = 0;
  return blocks
    .map((b) => {
      const text = htmlToMarkdownInline(b.content).trim();
      if (b.type !== 'numberedList') n = 0;
      switch (b.type) {
        case 'heading1': return `# ${text}`;
        case 'heading2': return `## ${text}`;
        case 'heading3': return `### ${text}`;
        case 'bulletList': return `- ${text}`;
        case 'numberedList': return `${++n}. ${text}`;
        case 'code': return '```\n' + text + '\n```';
        case 'quote': return text.split('\n').map((l) => `> ${l}`).join('\n');
        case 'divider': return '---';
        default: return text;
      }
    })
    .join('\n\n')
    .replace(/\n\n(- |\d+\. )/g, '\n$1') + '\n';
}
