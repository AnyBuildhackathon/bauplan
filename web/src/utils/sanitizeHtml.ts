// Adapted from core-oss (github.com/10xapp/core-oss, Apache-2.0),
// core-web/src/utils/sanitizeHtml.ts. Modified: only the strict config used by the
// block editor is kept.
import DOMPurify, { type Config } from "dompurify";

const STRICT_URI_REGEXP = /^(?:(?:https?|mailto|tel):|[^a-z]|[a-z+.-]+(?:[^a-z+.-:]|$))/i;

const STRICT_CONFIG: Config = {
  USE_PROFILES: { html: true },
  ALLOW_DATA_ATTR: false,
  ALLOWED_TAGS: ["a", "b", "blockquote", "br", "code", "em", "i", "li", "ol", "p", "pre", "s", "span", "strong", "u", "ul"],
  ALLOWED_ATTR: ["href", "target", "rel"],
  ALLOWED_URI_REGEXP: STRICT_URI_REGEXP,
};

/** Sanitize HTML and force all links to open in a new tab. */
export function sanitizeStrictHtml(html: string): string {
  if (!html) return "";
  DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    if (node.tagName === "A") {
      node.setAttribute("target", "_blank");
      node.setAttribute("rel", "noopener noreferrer");
    }
  });
  const result = DOMPurify.sanitize(html, STRICT_CONFIG);
  DOMPurify.removeHook("afterSanitizeAttributes");
  return result;
}
