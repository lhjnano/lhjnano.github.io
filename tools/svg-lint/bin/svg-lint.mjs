#!/usr/bin/env node
// tools/svg-lint/bin/svg-lint.mjs
// svg-lint — house-style checker for hand-written SVG diagrams.
// Zero dependencies on purpose: a bare clone must be able to run this.
import { readFileSync, writeFileSync } from 'node:fs';
import { lintSource } from '../lib/lint.mjs';
import { fixSource } from '../lib/fix.mjs';
import { summarize } from '../lib/report.mjs';
import { formatText } from '../lib/format-text.mjs';
import { formatJson } from '../lib/format-json.mjs';

const USAGE = `Usage: svg-lint [options] <file.svg...>

Options:
  --fix         apply the mechanically-safe fixes in place (writes <file>.bak)
  --json        emit machine-readable JSON instead of text
  --quiet       report errors only, suppress warnings
  -h, --help    show this help

Exit codes:
  0  no errors (warnings may still be present)
  1  at least one error
  2  bad usage, or an input file could not be read
`;

// Not exported: the CLI tests drive this through a spawned process, which is the contract that
// matters, so an export would widen the surface without adding a caller.
function parseArgv(argv) {
  const options = { fix: false, json: false, quiet: false, files: [] };
  for (const arg of argv) {
    if (arg === '--fix') options.fix = true;
    else if (arg === '--json') options.json = true;
    else if (arg === '--quiet') options.quiet = true;
    else if (arg === '-h' || arg === '--help') return { help: true, options };
    else if (arg.startsWith('-')) return { unknownOption: arg, options };
    else options.files.push(arg);
  }
  return { options };
}

function main(argv) {
  const parsed = parseArgv(argv);
  if (parsed.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  if (parsed.unknownOption) {
    process.stderr.write(`Unknown option: ${parsed.unknownOption}\n\n${USAGE}`);
    return 2;
  }
  const { files, json } = parsed.options;
  if (files.length === 0) {
    process.stderr.write(`No input files.\n\n${USAGE}`);
    return 2;
  }
  const sources = [];
  let unreadable = 0;
  for (const file of files) {
    try {
      sources.push({ file, source: readFileSync(file, 'utf8') });
    } catch (cause) {
      // One unreadable file should not make a whole batch run go mute: the list xargs passes in
      // may contain a path that was just deleted, and the verdicts on the other files are still worth having.
      process.stderr.write(`Cannot read ${file}: ${cause.message}\n`);
      unreadable += 1;
    }
  }
  if (sources.length === 0) return 2;

  // --fix rewrites each file in place after saving <file>.bak, and the lint
  // verdict below is computed on the FIXED source — what you would get by
  // running the checker again afterwards.
  if (parsed.options.fix) {
    for (const item of sources) {
      let fixed;
      try {
        fixed = fixSource(item.source);
      } catch (cause) {
        process.stderr.write(`Cannot fix ${item.file}: ${cause.message}\n`);
        continue;
      }
      if (fixed.applied.length === 0) continue;
      try {
        writeFileSync(`${item.file}.bak`, item.source, 'utf8');
        writeFileSync(item.file, fixed.source, 'utf8');
        item.source = fixed.source;
        process.stdout.write(`${item.file} — fixed in place (backup at ${item.file}.bak):\n`);
        for (const line of fixed.applied) process.stdout.write(`  · ${line}\n`);
      } catch (cause) {
        process.stderr.write(`Cannot write ${item.file}: ${cause.message}\n`);
      }
    }
  }

  const results = sources.map(({ file, source }) => lintSource(file, source));
  const summary = summarize(results);
  process.stdout.write(json ? formatJson(results, summary) : formatText(results, parsed.options));
  // A file that could not be read outranks the lint verdict: the report covers fewer files than
  // were asked for, so a clean 0 would claim more than was checked.
  return unreadable > 0 ? 2 : summary.exitCode;
}

// process.exit() drops output still queued when stdout is a pipe, because a pipe write is
// asynchronous. Measured on this machine: a batch printing past 64KB arrived cut off at 64390
// bytes. Setting exitCode lets Node exit once the queue has drained.
process.exitCode = main(process.argv.slice(2));
