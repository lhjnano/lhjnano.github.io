// tools/svg-lint/lib/registry.mjs
// The only entry point for adding a check: import a module and push it into CHECKS.
// Order here is run order only. It does not reach the output: lint.mjs sorts the findings by line,
// then column, then check id alphabetically, so two findings on one line come out in alphabetical
// order whatever this list says.
import { xmlEscaping } from './checks/xml-escaping.mjs';
import { viewboxClipping } from './checks/viewbox-clipping.mjs';
import { fontStack } from './checks/font-stack.mjs';
import { boxHeight } from './checks/box-height.mjs';
import { baselineOffset } from './checks/baseline-offset.mjs';
import { blockSpacing } from './checks/block-spacing.mjs';
import { arrowMarker } from './checks/arrow-marker.mjs';
import { textOverflow } from './checks/text-overflow.mjs';
import { overlap } from './checks/overlap.mjs';
import { boxClearance } from './checks/box-clearance.mjs';
import { textClearance } from './checks/text-clearance.mjs';
import { paddingBalance } from './checks/padding-balance.mjs';
import { lightBgFallback } from './checks/light-bg-fallback.mjs';
import { paletteConformance } from './checks/palette-conformance.mjs';
import { connectorGeometry } from './checks/connector-geometry.mjs';

export const CHECKS = [
  xmlEscaping,
  viewboxClipping,
  fontStack,          // re-enabled with a Korean stack (user request)
  boxHeight,
  baselineOffset,
  blockSpacing,
  arrowMarker,
  textOverflow,
  overlap,
  boxClearance,       // label ↔ box vertical breathing room (user request)
  textClearance,      // stacked text rows keep breathing room (user request)
  paddingBalance,     // balanced padding above/below text in boxes (user request)
  lightBgFallback,    // re-enabled (user request)
  paletteConformance,
  connectorGeometry,
];
