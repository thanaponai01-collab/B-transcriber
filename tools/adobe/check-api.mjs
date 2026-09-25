// Fails when the UXP panel reads a member name that exists nowhere it could come from:
// Adobe's typings, Adobe's docs, JS/DOM built-ins, or CutDeck's own code. That is the
// signature of an API written from memory (a method Premiere does not have).
//   node tools/adobe/check-api.mjs          -> report, exit 1 on unknown names
//   node tools/adobe/check-api.mjs --json   -> machine-readable result (used by the test)
// Limit: names are checked, not which class they sit on. `seq.getVideoTrack()` passes because
// Sequence has it; calling it on a TrackItem would pass too. Known-but-untyped names (helper
// RPC fields, probe-proven undocumented members) go in api-allowlist.json with a reason.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const here = path.dirname(fileURLToPath(import.meta.url));
const ts = createRequire(import.meta.url)("typescript");
const root = path.resolve(here, "..", "..");
const refDir = path.join(root, "reference", "adobe");
const panelArg = process.argv.find((a) => a.startsWith("--panel="));
const panelDir = panelArg ? path.resolve(panelArg.slice("--panel=".length)) : path.join(root, "uxp", "cutdeck");
const sources = JSON.parse(fs.readFileSync(path.join(refDir, "sources.json"), "utf8"));
const allowlist = JSON.parse(fs.readFileSync(path.join(here, "api-allowlist.json"), "utf8")).names;

function walkFiles(dir, keep) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name === "package") continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...walkFiles(p, keep));
    else if (keep(e.name)) out.push(p);
  }
  return out;
}

// Every declared member/type/namespace name in a .d.ts (or lib) file.
function declaredNames(sf, into) {
  const visit = (node) => {
    const n = node.name;
    if (n && (ts.isIdentifier(n) || ts.isStringLiteral(n) || ts.isPrivateIdentifier(n))) {
      if (ts.isPropertySignature(node) || ts.isMethodSignature(node) || ts.isPropertyDeclaration(node) ||
          ts.isMethodDeclaration(node) || ts.isGetAccessor(node) || ts.isSetAccessor(node) ||
          ts.isEnumMember(node) || ts.isClassDeclaration(node) || ts.isInterfaceDeclaration(node) ||
          ts.isTypeAliasDeclaration(node) || ts.isModuleDeclaration(node) || ts.isVariableDeclaration(node) ||
          ts.isFunctionDeclaration(node) || ts.isEnumDeclaration(node)) into.add(n.text);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
}

const parse = (file) => ts.createSourceFile(file, fs.readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true);

// 1. Adobe typings (every pinned version).
const adobeTyped = new Set();
for (const t of sources.typings) declaredNames(parse(path.join(refDir, "typings", t.saveAs)), adobeTyped);
const premiere265 = new Set(), premiere262 = new Set();
declaredNames(parse(path.join(refDir, "typings", "premierepro-26.5.1.d.ts")), premiere265);
declaredNames(parse(path.join(refDir, "typings", "premierepro-26.2.1.d.ts")), premiere262);

// 2. Adobe docs + samples: names written as `.name` in the markdown / sample code.
const adobeDocs = new Set();
for (const f of walkFiles(refDir, (n) => /\.(md|js|ts|tsx|jsx)$/.test(n))) {
  for (const m of fs.readFileSync(f, "utf8").matchAll(/\.([A-Za-z_$][\w$]*)/g)) adobeDocs.add(m[1]);
}

// 3. JS + DOM built-ins, from TypeScript's own lib files.
const builtins = new Set();
const libDir = path.dirname(createRequire(import.meta.url).resolve("typescript/lib/lib.d.ts"));
for (const f of fs.readdirSync(libDir)) {
  if (/^lib\.(es\d{4}|es5|esnext|dom|decorators|scripthost|webworker\.importscripts).*\.d\.ts$/.test(f)) declaredNames(parse(path.join(libDir, f)), builtins);
}

// 4. CutDeck's own code: every name the panel defines on an object.
const panelFiles = walkFiles(panelDir, (n) => n.endsWith(".js"));
const own = new Set();
const panelAsts = panelFiles.map((f) => [f, parse(f)]);
for (const [, sf] of panelAsts) {
  const visit = (node) => {
    const nameText = (n) => (n && (ts.isIdentifier(n) || ts.isStringLiteral(n) || ts.isNumericLiteral(n)) ? n.text : null);
    if (ts.isPropertyAssignment(node) || ts.isMethodDeclaration(node) || ts.isGetAccessor(node) ||
        ts.isSetAccessor(node) || ts.isPropertyDeclaration(node) || ts.isFunctionDeclaration(node) ||
        ts.isShorthandPropertyAssignment(node)) {
      const t = nameText(node.name);
      if (t) own.add(t);
    } else if (ts.isBindingElement(node)) {
      const t = nameText(node.propertyName) || nameText(node.name);
      if (t) own.add(t);
    } else if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
               ts.isPropertyAccessExpression(node.left)) {
      own.add(node.left.name.text);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
}

// 5. The CutDeck helper's reply fields (job.result_name, plan.placements, ...): every quoted
//    snake/lower-case string in the Python helper package, the protocol's source of truth.
const helper = new Set();
for (const f of walkFiles(path.join(root, "cutdeck"), (n) => n.endsWith(".py"))) {
  for (const m of fs.readFileSync(f, "utf8").matchAll(/["']([a-z_][a-z0-9_]*)["']/g)) helper.add(m[1]);
}
// Option bags the panel's own callers fill in (`opts.timeoutMs`, `deps.al`): never Adobe objects.
const OPTION_BAGS = new Set(["opts", "options", "deps"]);

// Every `x.name` the panel reads.
const unknown = [];
const needs263 = [];
for (const [file, sf] of panelAsts) {
  const rel = path.relative(root, file).replace(/\\/g, "/");
  const visit = (node) => {
    if (ts.isPropertyAccessExpression(node) && ts.isIdentifier(node.name)) {
      const name = node.name.text;
      const where = `${rel}:${sf.getLineAndCharacterOfPosition(node.name.getStart(sf)).line + 1}`;
      const bag = ts.isIdentifier(node.expression) && OPTION_BAGS.has(node.expression.text);
      const known = bag || adobeTyped.has(name) || adobeDocs.has(name) || builtins.has(name) || own.has(name) ||
        helper.has(name) || name in allowlist;
      if (!known) unknown.push({ name, where, code: node.getText(sf).slice(0, 80) });
      else if (premiere265.has(name) && !premiere262.has(name) && !builtins.has(name) && !own.has(name)) needs263.push({ name, where });
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
}

const staleAllow = Object.keys(allowlist).filter((n) => adobeTyped.has(n) || builtins.has(n) || own.has(n));
const result = { files: panelFiles.length, unknown, needs263, staleAllow };
if (process.argv.includes("--json")) {
  process.stdout.write(JSON.stringify(result));
} else {
  console.log(`Checked ${panelFiles.length} panel files against reference/adobe/ (typings ${sources.typings.map((t) => `${t.package}@${t.version}`).join(", ")}).`);
  if (needs263.length) {
    console.log(`\nInfo: ${needs263.length} use(s) of Premiere members absent from the 26.2.1 typings (manifest minVersion 26.2.0):`);
    for (const u of needs263) console.log(`  ${u.name.padEnd(36)} ${u.where}`);
  }
  if (staleAllow.length) console.log(`\nAllowlist entries now known elsewhere (remove them): ${staleAllow.join(", ")}`);
  if (unknown.length) {
    console.log(`\nFAIL: ${unknown.length} member name(s) found in no Adobe typings, Adobe docs, built-ins or CutDeck code:`);
    for (const u of unknown) console.log(`  ${u.name.padEnd(36)} ${u.where}   ${u.code}`);
    console.log("\nLook each up in reference/adobe/ (api/*.txt, docs/). Real but untyped -> add to tools/adobe/api-allowlist.json with the proof. Not real -> it was written from memory; fix it.");
    process.exitCode = 1;
  } else {
    console.log("\nOK: every member name the panel reads is accounted for.");
  }
}
