// tools/svg-lint/lib/checks/empty-box.mjs
// A content-sized box with no label inside it is almost always a rendering bug:
// the author deleted the text, a placeholder never got filled, or a panel was
// duplicated without its contents. The eye catches it instantly on the rendered
// page; the linter should catch it before that.
//
// What counts as "labelled": any text whose centre falls inside the box, or
// another content box nested inside (grouping panels legitimately hold boxes,
// not words). What is exempt: swatches, bars, dividers (too small), and the
// canvas/panel-sized rects (too big to be a single label slot).
import { error } from '../report.mjs';
import { pointInBBox } from '../geometry.mjs';

const ID = 'empty-box';

const MIN_W = 60;      // legend swatches and accent bars stay below this
const MIN_H = 25;      // dividers and underlines stay below this
const MAX_AREA = 200000; // canvas-sized rects and outer panels stay above this

const centerOf = (r) => ({
  x: (r.bbox.minX + r.bbox.maxX) / 2,
  y: (r.bbox.minY + r.bbox.maxY) / 2,
});

export const emptyBox = {
  id: ID,
  title: 'Content boxes carry a label',
  run(doc) {
    const out = [];
    for (const rect of doc.contentRects) {
      if (rect.width < MIN_W || rect.height < MIN_H) continue;
      if (rect.width * rect.height > MAX_AREA) continue;
      const holdsText = doc.texts.some((t) => pointInBBox(t.center, rect.bbox));
      if (holdsText) continue;
      const holdsBox = doc.contentRects.some(
        (o) => o !== rect && pointInBBox(centerOf(o), rect.bbox),
      );
      if (holdsBox) continue;
      out.push(error({
        check: ID, code: 'unlabelled-box', line: rect.line, column: rect.column,
        message: `A ${Math.round(rect.width)}×${Math.round(rect.height)}px box has no label inside it`,
        repair: {
          hint: 'add the missing text, delete the empty box, or shrink it below label size',
        },
      }));
    }
    return out;
  },
};
