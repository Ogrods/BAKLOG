/**
 * Typed spotlight metaParts: { text } is escaped; { html } is trusted markup.
 * Legacy plain strings are treated as already-safe HTML (app-built fragments).
 */
import { escapeHtml } from './dom-util.js';

/** @param {unknown} s */
export function metaText(s) {
  return { text: String(s ?? '') };
}

/** @param {unknown} s */
export function metaHtml(s) {
  return { html: String(s ?? '') };
}

/**
 * @param {unknown} part
 * @returns {string}
 */
export function renderMetaPart(part) {
  if (part == null || part === '') return '';
  if (typeof part === 'string') return part;
  if (typeof part === 'object') {
    if (typeof part.html === 'string') return part.html;
    if (typeof part.text === 'string') return escapeHtml(part.text);
  }
  return '';
}

/**
 * @param {unknown[] | null | undefined} parts
 * @returns {string}
 */
export function renderMetaParts(parts) {
  if (!Array.isArray(parts) || !parts.length) return '';
  return parts.map(renderMetaPart).filter(Boolean).join(' · ');
}
