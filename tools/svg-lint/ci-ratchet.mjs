#!/usr/bin/env node
// tools/svg-lint/ci-ratchet.mjs
// Baseline-ratchet CI mode: fails only when a file regresses beyond its
// baseline error count, or when a NEW file introduces errors. Existing debt
// (legacy AWS diagrams, pre-governance inline SVGs) is tracked so it can be
// ratcheted down over time instead of blocking every push.
//
// Usage:
//   node tools/svg-lint/ci-ratchet.mjs            # CI check (exit 1 on regression)
//   node tools/svg-lint/ci-ratchet.mjs --update   # regenerate baseline.json
import { readFileSync, writeFileSync, readdirSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';

const ROOT = path.resolve(import.meta.dirname, '..', '..');
const LINTER = path.join(ROOT, 'tools/svg-lint/bin/svg-lint.mjs');
const BASELINE = path.join(ROOT, 'tools/svg-lint/baseline.json');
const UPDATE = process.argv.includes('--update');

// ── collect targets: inline markdown SVGs + standalone files ──
const targets = new Map(); // name -> { svg, origin }
const postsDir = path.join(ROOT, '_posts');
for (const fn of readdirSync(postsDir).filter(f => f.endsWith('.md'))) {
  const src = readFileSync(path.join(postsDir, fn), 'utf8');
  const svgs = src.match(/<svg[^>]*>[\s\S]*?<\/svg>/g) || [];
  svgs.forEach((svg, i) => {
    targets.set(`inline:${fn.replace(/\.md$/, '')}#${i}`, { svg, origin: 'markdown' });
  });
}
const imagesDir = path.join(ROOT, 'assets/images');
const walk = (dir) => {
  if (!existsSync(dir)) return;
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p);
    else if (e.name.endsWith('.svg')) targets.set(`file:${path.relative(ROOT, p)}`, { file: p, origin: 'file' });
  }
};
walk(imagesDir);

// ── lint every target, count errors from JSON output ──
// svg-lint exits 1 when it finds errors — in --json mode the report is still
// valid on stdout, so capture the throw instead of letting it kill the run.
const lintJson = (args) => {
  try {
    return JSON.parse(execFileSync('node', [LINTER, '--json', '--quiet', ...args], { encoding: 'utf8' }));
  } catch (err) {
    if (err.status === 1 && err.stdout) return JSON.parse(err.stdout);
    throw err;
  }
};

const current = {};
for (const [name, t] of targets) {
  let json;
  if (t.origin === 'markdown') {
    const tmp = path.join('/tmp', `ratchet-${name.replace(/[^a-z0-9:#.-]/gi, '_')}.svg`);
    writeFileSync(tmp, t.svg);
    json = lintJson([tmp]);
  } else {
    json = lintJson([t.file]);
  }
  current[name] = json.summary?.errors ?? 0;
}

const baseline = existsSync(BASELINE)
  ? JSON.parse(readFileSync(BASELINE, 'utf8'))
  : {};

if (UPDATE) {
  writeFileSync(BASELINE, JSON.stringify(current, null, 2) + '\n');
  const total = Object.values(current).reduce((a, b) => a + b, 0);
  console.log(`baseline.json 갱신: ${Object.keys(current).length}개 항목, 총 에러 ${total}개`);
  process.exit(0);
}

// ── compare against baseline ──
const regressions = [];
const improvements = [];
let currentTotal = 0, baselineTotal = 0;
for (const [name, count] of Object.entries(current)) {
  currentTotal += count;
  const base = baseline[name] ?? 0;
  baselineTotal += base;
  if (count > base) regressions.push([name, base, count]);
  else if (count < base) improvements.push([name, base, count]);
}
const removed = Object.keys(baseline).filter(k => !(k in current) && baseline[k] > 0);

console.log(`대상: ${Object.keys(current).length}개 SVG (인라인 + standalone)`);
console.log(`래칫 현황: baseline ${baselineTotal} → 현재 ${currentTotal} 에러`);
if (improvements.length) {
  console.log(`\n개선 (${improvements.length}개):`);
  for (const [n, b, c] of improvements.slice(0, 10)) console.log(`  ✅ ${n}: ${b} → ${c}`);
  if (improvements.length > 10) console.log(`  … 외 ${improvements.length - 10}개`);
}
if (removed.length) {
  console.log(`\n해결 (${removed.length}개):`);
  for (const n of removed.slice(0, 10)) console.log(`  🎉 ${n}: ${baseline[n]} → 0 (파일 삭제/정리)`);
}
if (regressions.length) {
  console.log(`\n악화 (${regressions.length}개):`);
  for (const [n, b, c] of regressions) console.log(`  ❌ ${n}: ${b} → ${c}`);
  console.error(`\n::error::${regressions.length}개 SVG가 baseline보다 악화됨`);
  process.exit(1);
}
console.log('\n✅ regression 없음 — baseline 유지 또는 개선');
process.exit(0);
