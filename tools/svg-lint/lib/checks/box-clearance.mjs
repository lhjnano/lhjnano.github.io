// tools/svg-lint/lib/checks/box-clearance.mjs
// A label that floats above or below a box — horizontally overlapping its
// span — must keep MIN_CLEARANCE px of vertical breathing room from that
// box's edge. The connector/curve clearance rules never measure flat box
// edges, and text-over-box only fires on actual overlap, so a header parked
// 11px above a card used to pass in silence. Horizontal proximity beside a
// box is deliberately not measured here: text-overflow/text-intrudes-neighbor
// owns that case, and measuring it twice would double-report one problem.
import { warning } from '../report.mjs';

const ID = 'box-clearance';
const MIN_CLEARANCE = 15;
const round = (v) => Number(v.toFixed(1));

// Axis-aligned gap: 0 on an axis means the spans overlap on that axis.
const axisGap = (aMin, aMax, bMin, bMax) => Math.max(bMin - aMax, aMin - bMax, 0);

const pointInBBox = (p, b) => p.x >= b.minX && p.x <= b.maxX && p.y >= b.minY && p.y <= b.maxY;

export const boxClearance = {
  id: ID,
  title: 'Labels keep vertical breathing room above and below boxes',
  run(doc) {
    const out = [];

    // Box-like shapes: real <rect> boxes plus closed, substantially
    // two-dimensional paths — cards drawn with rounded corners (matplotlib
    // exports, FancyBboxPatch) never appear in contentRects. Connector paths
    // are open; marker arrowheads are closed but tiny, so the 16px floor on
    // both dimensions keeps them out.
    const shapes = [
      ...doc.contentRects,
      ...doc.groupRects,
      ...doc.paths.filter((p) => {
        if (!/(z|Z)\s*$/.test(p.d.trim())) return false;
        const w = p.bbox.maxX - p.bbox.minX;
        const h = p.bbox.maxY - p.bbox.minY;
        return w >= 16 && h >= 16 && p.points.length >= 4;
      }),
    ];

    for (const t of doc.texts) {
      for (const s of shapes) {
        // A text whose centre is inside the shape is that shape's own label
        // (or an overlap the overlap check owns) — not a breathing-room case.
        if (pointInBBox(t.center, s.bbox)) continue;

        const dx = axisGap(t.bbox.minX, t.bbox.maxX, s.bbox.minX, s.bbox.maxX);
        const dy = axisGap(t.bbox.minY, t.bbox.maxY, s.bbox.minY, s.bbox.maxY);

        // Only the vertical case: spans overlap horizontally (dx === 0) and
        // the text sits clear above or below (dy > 0) but too close.
        if (dx > 0) continue;
        if (dy === 0) continue; // touching or overlapping: overlap/text-over-box owns it
        if (dy >= MIN_CLEARANCE) continue;

        const where = t.center.y < s.bbox.minY ? 'above' : 'below';
        out.push(warning({
          check: ID, code: 'label-too-close', line: t.line, column: t.column,
          message: `Label ${JSON.stringify(t.content.slice(0, 40))} sits ${round(dy)}px ${where} a box; the minimum breathing room is ${MIN_CLEARANCE}px`,
          repair: {
            actual: String(round(dy)),
            expected: `≥${MIN_CLEARANCE}`,
            hint: 'move the label further from the box, or give the box top padding and put the label inside it',
          },
        }));
      }
    }
    return out;
  },
};
