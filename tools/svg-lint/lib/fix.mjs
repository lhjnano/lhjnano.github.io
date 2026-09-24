// tools/svg-lint/lib/fix.mjs
// --fix applies the mechanically-safe subset of repairs. Geometry findings
// (box heights, block spacing, baselines) are deliberate layout decisions and
// stay report-only. Every fix here is idempotent: running it twice changes
// nothing the second time.
import { parseSvg } from './parse-svg.mjs';
import { buildDocument } from './document.mjs';
import { textBBox } from './text-metrics.mjs';

export const FONT_STACK = "'Noto Sans KR', 'Apple SD Gothic Neo', 'Malgun Gothic', system-ui, sans-serif";

// Raw "&" that is not already part of an entity reference. CDATA sections are
// not excluded: hand-written diagrams do not carry them, and the trade for a
// regex this simple is recorded here rather than hidden.
const RAW_AMPERSAND = /&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)/g;

// viewBox margin target for the recompute fix — the middle of the 20–25 band.
const MARGIN = 22;
const MARGIN_MIN = 20;
const MARGIN_MAX = 25;

const round1 = (v) => Number(v.toFixed(1));

function viewBoxOf(source) {
  const m = source.match(/<svg\b[^>]*\bviewBox\s*=\s*"([^"]+)"/);
  if (!m) return null;
  const n = m[1].trim().split(/[\s,]+/).map(Number);
  return n.length === 4 && n.every(Number.isFinite) ? { x: n[0], y: n[1], w: n[2], h: n[3] } : null;
}

function hasWhiteCanvas(source, vb) {
  for (const tag of source.matchAll(/<rect\b[^>]*>/gi)) {
    const fill = tag[0].match(/\bfill\s*=\s*"#fff(?:fff)?"/i);
    if (!fill) continue;
    const w = tag[0].match(/\bwidth\s*=\s*"([\d.]+)"/);
    const h = tag[0].match(/\bheight\s*=\s*"([\d.]+)"/);
    if (w && h && +w[1] >= vb.w - 1 && +h[1] >= vb.h - 1) return true;
  }
  return false;
}

function fixMarkerUnits(s, applied) {
  let n = 0;
  const out = s.replace(/<marker\b[^>]*>/gi, (tag) => {
    if (/\bmarkerUnits\s*=/i.test(tag)) return tag;
    const selfClosing = tag.endsWith('/>');
    const attrs = tag.slice('<marker'.length, selfClosing ? -2 : -1).trim();
    n += 1;
    return `<marker ${attrs} markerUnits="userSpaceOnUse"${selfClosing ? ' /' : ''}>`;
  });
  if (n > 0) applied.push(`arrow-marker: added markerUnits="userSpaceOnUse" to ${n} marker(s)`);
  return out;
}

export function fixSource(source) {
  const applied = [];
  let s = source;

  // 1. XML escaping — safe by construction, idempotent via the lookahead.
  const escaped = s.replace(RAW_AMPERSAND, '&amp;');
  if (escaped !== s) {
    applied.push('xml-escaping: escaped raw & as &amp;');
    s = escaped;
  }

  // 2. viewBox margin recompute — runs on the ORIGINAL content (before the
  // white canvas rect is inserted below, which would otherwise span the whole
  // viewBox and make every margin read as 0). Skipped when the model notes an
  // unsupported transform: the bbox it would act on may be wrong.
  let doc = null;
  try {
    doc = buildDocument(parseSvg(s));
  } catch {
    doc = null; // fixes that need the model are skipped; the rest still run
  }
  const vbOrig = viewBoxOf(s);
  if (doc && doc.contentBBox && vbOrig && !doc.notes.some((n) => n.code === 'unsupported-transform')) {
    const b = doc.contentBBox;
    const x = round1(b.minX - MARGIN);
    const y = round1(b.minY - MARGIN);
    const w = round1(b.maxX - b.minX + 2 * MARGIN);
    const h = round1(b.maxY - b.minY + 2 * MARGIN);
    const differs = Math.abs(x - vbOrig.x) > 0.05 || Math.abs(y - vbOrig.y) > 0.05
      || Math.abs(w - vbOrig.w) > 0.05 || Math.abs(h - vbOrig.h) > 0.05;
    const outOfBand = vbOrig.x + MARGIN_MIN > b.minX || b.minX - vbOrig.x > MARGIN_MAX
      || vbOrig.y + MARGIN_MIN > b.minY || b.minY - vbOrig.y > MARGIN_MAX
      || vbOrig.x + vbOrig.w - MARGIN_MIN < b.maxX || b.maxX - (vbOrig.x + vbOrig.w) > MARGIN_MAX
      || vbOrig.y + vbOrig.h - MARGIN_MIN < b.maxY || b.maxY - (vbOrig.y + vbOrig.h) > MARGIN_MAX;
    if (differs && outOfBand) {
      const newVB = `${x} ${y} ${w} ${h}`;
      s = s.replace(/(<svg\b[^>]*\bviewBox\s*=\s*)"[^"]*"/i, `$1"${newVB}"`);
      vbOrig.x = x; vbOrig.y = y; vbOrig.w = w; vbOrig.h = h; // the fixes below size from this
      applied.push(`viewbox-clipping: recomputed viewBox to "${newVB}" (${MARGIN}px margins)`);
      // A resized viewBox and a stale width disagree on the display size;
      // the house rule is width = viewBox width. Units are preserved: matplotlib
      // writes width="963pt", and 963pt ≠ 1007 user units.
      if (/<svg\b[^>]*\bwidth\s*=\s*"[\d.]+(?:pt|px|%|em)?"/i.test(s)) {
        s = s.replace(/(<svg\b[^>]*\bwidth\s*=\s*")[\d.]+((?:pt|px|%|em)?")/i, `$1${w}$2`);
      }
    }
  }

  // 3. width attribute — from the (possibly recomputed) viewBox.
  const svgOpen = s.match(/<svg\b[^>]*>/);
  if (svgOpen && vbOrig && !/\bwidth\s*=/.test(svgOpen[0])) {
    s = s.replace(svgOpen[0], svgOpen[0].replace(/<svg\b/, `<svg width="${vbOrig.w}"`));
    applied.push(`viewbox-clipping: added width="${vbOrig.w}"`);
  }

  // 4. White canvas rect — inserted as the first child of <svg> so it paints
  // behind everything.
  if (vbOrig && !hasWhiteCanvas(s, vbOrig)) {
    const open = s.match(/<svg\b[^>]*>/);
    s = s.replace(open[0], `${open[0]}<rect x="${vbOrig.x}" y="${vbOrig.y}" width="${vbOrig.w}" height="${vbOrig.h}" fill="#ffffff"/>`);
    applied.push('light-bg-fallback: inserted white canvas rect');
  }

  // 5. Font stacks — two parts. Any font-family declaration that does not
  // carry the whole Hangul stack is rewritten to the canonical one (a
  // per-text style attribute overrides any <style> rule, so inserting the
  // rule alone would not fix the checker's verdict). Then a <style> rule for
  // text is inserted only when no <style> block declares font-family — the
  // detection is bounded to the block, because an unbounded search reaches
  // inline declarations further down the file and never fires.
  {
    // Order matters as much as presence: the checker requires the primary
    // (Noto Sans KR) before the fallbacks, so a stack that merely contains
    // all three in the wrong order must be rewritten too.
    const ORDER = ['noto sans kr', 'apple sd gothic neo', 'malgun gothic'];
    const compliant = (decl) => {
      const positions = ORDER.map((f) => decl.toLowerCase().indexOf(f));
      return positions.every((p) => p !== -1)
        && positions.every((p, i) => i === 0 || positions[i - 1] < p);
    };
    let rewritten = 0;
    s = s.replace(/font-family\s*:\s*[^;"}]+/g, (decl) => {
      if (compliant(decl)) return decl;
      rewritten += 1;
      return `font-family: ${FONT_STACK}`;
    });
    if (rewritten > 0) applied.push(`font-stack: rewrote ${rewritten} font-family declaration(s) to the Hangul stack`);
    const styleDeclares = [...s.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)]
      .some((m) => /font-family\s*:/.test(m[1]));
    if (!styleDeclares) {
      const open = s.match(/<svg\b[^>]*>/);
      s = s.replace(open[0], `${open[0]}<style>text{font-family:${FONT_STACK};}</style>`);
      applied.push('font-stack: inserted the Hangul font stack <style> rule');
    }
  }

  // 6. markerUnits on <marker> definitions.
  s = fixMarkerUnits(s, applied);

  // NOTE: textLength pinning was tried and removed. The linter's char-width
  // tables estimate Korean/Latin text within ~10–20% of any real font, and a
  // pinned textLength forces the renderer to absorb that whole error — as
  // stretched glyphs (spacingAndGlyphs) or as gaping letter-spacing
  // (spacing). Pinning with estimated widths distorts by exactly the
  // estimation error, so the fix for font-dependent overflow belongs at the
  // export source (matching font metrics), not here.

  return { source: s, applied };
}
