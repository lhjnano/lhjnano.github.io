// tools/svg-lint/lib/palette.mjs
// The sole numeric source for the house palette, copied verbatim from SKILL.md "Colors" and "Arrowhead definitions".
// All check modules must read values from here; writing hex literals inline is not allowed.

export const BASE_TEXT = {
  primary: '#1e293b',
  secondary: '#64748b',
  muted: '#94a3b8',
};

export const SEMANTIC = [
  { name: 'input', fill: '#dbeafe', stroke: '#3b82f6', text: '#1e40af' },
  { name: 'processing', fill: '#fef3c7', stroke: '#f59e0b', text: '#b45309' },
  { name: 'output', fill: '#d1fae5', stroke: '#22c55e', text: '#166534' },
  { name: 'analysis', fill: '#f3e8ff', stroke: '#a855f7', text: '#6b21a8' },
  { name: 'warning', fill: '#fce7f3', stroke: '#ec4899', text: '#9d174d' },
];

export const ARROW_COLORS = {
  arrow: '#64748b',
  'arrow-blue': '#3b82f6',
  'arrow-orange': '#f59e0b',
  'arrow-green': '#22c55e',
  'arrow-purple': '#a855f7',
  'arrow-red': '#ef4444',
};

export const GROUP_BOX = {
  fill: '#f8fafc',
  stroke: '#94a3b8',
  dasharray: '6,4',
};

export const ALLOWED_COLORS = new Set([
  ...Object.values(BASE_TEXT),
  ...SEMANTIC.flatMap((s) => [s.fill, s.stroke, s.text]),
  ...Object.values(ARROW_COLORS),
  GROUP_BOX.fill,
  GROUP_BOX.stroke,
  'none',
  '#ffffff',
]);

// ─── USER CUSTOMIZATION (top-20 palette, user-selected strictness) ───
// The 20 most-used colors across the ~/documents SVG corpus (GitHub-dark +
// Material house style), normalized to 6-digit lowercase hex. This REPLACES
// the bybit house palette as the allowed set. Comparison is numeric, so
// #abc == #aabbcc and rgb()/rgba() alpha is ignored (alpha composites against
// the embedding page, which this file cannot see).
export const USER_COLORS = new Set([
  '#546e7a', '#8b949e', '#37474f', '#3fb950', '#ffffff',
  '#78909c', '#58a6ff', '#263238', '#f85149', '#e6edf3',
  '#161b22', '#555555', '#1976d2', '#30363d', '#bc8cff',
  '#0d47a1', '#8892aa', '#888888', '#e3f2fd', '#1565c0',
  '#22d3ee',
  // ── Blog palette (github_page governance 3.5.2) ──
  '#666666',  // 중립 stroke (최다 사용 244회)
  '#16a34a',  // 서버/성공 stroke (157회)
  '#2c3e50',  // 본문 텍스트 (79회)
  '#dc2626',  // 경고 stroke (62회)
  '#2563eb',  // 클라이언트 stroke (61회)
  '#f0f4f8',  // 중립 fill (58회)
  '#495057',  // 서브텍스트 (56회)
  '#92400e',  // 정보 텍스트 (50회)
  '#dcfce7',  // 서버/성공 fill (44회)
  '#fbbf24',  // 정보 stroke (43회)
  '#fef3c7',  // 정보 fill (27회)
  '#7c3aed',  // 네트워크 stroke (21회)
  '#dbeafe',  // 클라이언트 fill (16회)
  '#fef2f2',  // 경고 fill (16회)
  '#dddddd',  // 라이프라인 (11회)
  '#999999',  // 보조 (6회)
  '#ede9fe',  // 네트워크 fill (4회)
  '#cbd5e1',  // 점선 (2회)
  '#e2e8f0',  // 구분선 (1회)
]);
// CSS custom properties (var(--accent), …) resolve in the embedding HTML page,
// not inside the SVG file — the linter cannot judge them, so it doesn't.
const CSS_VARIABLE = /^var\(/i;
const HEX3 = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i;
const HEX6 = /^#[0-9a-f]{6}$/i;
const RGB = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i;
// CSS colour names that appear in the corpus; compared numerically like the rest.
const CSS_NAMES = {
  white: '#ffffff', black: '#000000', red: '#ff0000', lime: '#00ff00',
  blue: '#0000ff', yellow: '#ffff00', cyan: '#00ffff', aqua: '#00ffff',
  magenta: '#ff00ff', fuchsia: '#ff00ff', silver: '#c0c0c0', gray: '#808080',
  grey: '#808080', maroon: '#800000', olive: '#808000', green: '#008000',
  purple: '#800080', teal: '#008080', navy: '#000080', orange: '#ffa500',
};
const toHex = (v) => {
  const s = String(v).trim().toLowerCase();
  let m;
  if ((m = s.match(HEX3))) return '#' + m[1] + m[1] + m[2] + m[2] + m[3] + m[3];
  if (HEX6.test(s)) return s;
  if (CSS_NAMES[s]) return CSS_NAMES[s];
  if ((m = s.match(RGB))) {
    return '#' + m.slice(1).map((n) => (+n).toString(16).padStart(2, '0')).join('');
  }
  return null;
};
export const isAllowedColor = (value) => {
  if (CSS_VARIABLE.test(value)) return true;
  // bybit ALLOWED_COLORS deliberately NOT consulted — the user's top-20 set
  // replaces the house palette (user request).
  const hex = toHex(value);
  return hex !== null && USER_COLORS.has(hex);
};

export const semanticByFill = (hex) => SEMANTIC.find((s) => s.fill === hex);
export const semanticByStroke = (hex) => SEMANTIC.find((s) => s.stroke === hex);
