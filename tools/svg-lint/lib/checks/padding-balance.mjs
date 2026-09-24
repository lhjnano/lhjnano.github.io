// tools/svg-lint/lib/checks/padding-balance.mjs
// The whitespace inside a box above its first line and below its last line
// should be balanced. A card with 24px of headroom and 60px below the last
// bullet looks unfinished — the reader sees a hole. Flags bottom-heavy boxes
// (bottom gap exceeding top gap by more than IMBALANCE px). Box-like shapes
// include closed paths (rounded-corner cards drawn as paths), so matplotlib
// exports are covered too.
import { warning } from '../report.mjs';

const ID = 'padding-balance';
const IMBALANCE = 20;
const round = (v) => Number(v.toFixed(1));

const pointInBBox = (p, b) => p.x >= b.minX && p.x <= b.maxX && p.y >= b.minY && p.y <= b.maxY;

export const paddingBalance = {
  id: ID,
  title: 'Boxes balance the padding above and below their text',
  run(doc) {
    const out = [];
    const shapes = [
      ...doc.contentRects,
      ...doc.paths.filter((p) => {
        if (!/(z|Z)\s*$/.test(p.d.trim())) return false;
        const w = p.bbox.maxX - p.bbox.minX;
        const h = p.bbox.maxY - p.bbox.minY;
        return w >= 16 && h >= 16 && p.points.length >= 4;
      }),
    ];
    for (const s of shapes) {
      const inside = doc.texts.filter((t) => pointInBBox(t.center, s.bbox));
      if (inside.length === 0) continue;
      const topText = Math.min(...inside.map((t) => t.bbox.minY));
      const bottomText = Math.max(...inside.map((t) => t.bbox.maxY));
      const topGap = topText - s.bbox.minY;
      const bottomGap = s.bbox.maxY - bottomText;
      if (bottomGap - topGap > IMBALANCE) {
        out.push(warning({
          check: ID, code: 'bottom-heavy', line: s.line ?? 1, column: s.column ?? 1,
          message: `Box has ${round(topGap)}px above its first line but ${round(bottomGap)}px below its last; the imbalance exceeds ${IMBALANCE}px`,
          repair: {
            actual: `${round(topGap)} / ${round(bottomGap)} (top / bottom)`,
            expected: `difference ≤ ${IMBALANCE}px`,
            hint: 'shrink the box height to hug its content, or redistribute the lines',
          },
        }));
      }
    }
    return out;
  },
};
