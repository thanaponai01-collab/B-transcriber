const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const uxpDir = path.join(root, "uxp", "cutdeck");

/* Structure rules keep the panel's layers and single-owner invariants from drifting.
   Each entry in KNOWN_EXCEPTIONS represents existing drift documented in
   docs/arch-design-cutdeck-panel.md and is tagged with the move number that eliminates it.
   Adding an entry here is a deliberate architectural decision (see docs/arch-design-cutdeck-panel.md),
   never a way to quiet this test: this table must only shrink as refactoring moves land. */
const KNOWN_EXCEPTIONS = {
  // (a) executeTransaction( allowed only in host/project.js
  executeTransaction: [],
  // (b) 254016000000 / TICKS_PER_SECOND = allowed only in host/ticks.js
  ticks: [],
  // (c) Layer direction: parse every require("./…") and fail when lower layer requires higher layer
  layerDirection: [],
  // (d) require("premierepro") at module scope allowed only in main.js
  premiereproModuleScope: [],
};

function panelJsFiles(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "package" || entry.name === "node_modules") continue;
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...panelJsFiles(p));
    else if (entry.name.endsWith(".js")) out.push(p);
  }
  return out;
}

function stripComments(source) {
  let out = "";
  let i = 0;
  let inLine = false;
  let inBlock = false;
  let inString = null;

  while (i < source.length) {
    const ch = source[i];
    const next = source[i + 1];

    if (inLine) {
      if (ch === "\n") { inLine = false; out += ch; }
      i++;
    } else if (inBlock) {
      if (ch === "*" && next === "/") { inBlock = false; i += 2; }
      else { if (ch === "\n") out += "\n"; i++; }
    } else if (inString) {
      out += ch;
      if (ch === "\\") { out += next || ""; i += 2; }
      else if (ch === inString) { inString = null; i++; }
      else i++;
    } else {
      if (ch === "/" && next === "/") { inLine = true; i += 2; }
      else if (ch === "/" && next === "*") { inBlock = true; i += 2; }
      else if (ch === '"' || ch === "'" || ch === "`") { inString = ch; out += ch; i++; }
      else { out += ch; i++; }
    }
  }
  return out;
}

// Extract require calls: returns array of { module, line, isModuleScope }
function extractRequires(source) {
  const results = [];
  let i = 0;
  let line = 1;
  let braceDepth = 0;

  while (i < source.length) {
    const ch = source[i];
    const next = source[i + 1];

    if (ch === "\n") {
      line++;
      i++;
    } else if (ch === "/" && next === "/") {
      i += 2;
      while (i < source.length && source[i] !== "\n") i++;
    } else if (ch === "/" && next === "*") {
      i += 2;
      while (i < source.length && !(source[i] === "*" && source[i + 1] === "/")) {
        if (source[i] === "\n") line++;
        i++;
      }
      i += 2;
    } else if (ch === "{") {
      braceDepth++;
      i++;
    } else if (ch === "}") {
      if (braceDepth > 0) braceDepth--;
      i++;
    } else if (ch === '"' || ch === "'" || ch === "`") {
      const quote = ch;
      i++;
      while (i < source.length && source[i] !== quote) {
        if (source[i] === "\\") i += 2;
        else {
          if (source[i] === "\n") line++;
          i++;
        }
      }
      i++;
    } else if (source.slice(i, i + 7) === "require") {
      const prev = i > 0 ? source[i - 1] : " ";
      if (!/[a-zA-Z0-9_$]/.test(prev)) {
        let j = i + 7;
        while (j < source.length && /\s/.test(source[j])) {
          if (source[j] === "\n") line++;
          j++;
        }
        if (source[j] === "(") {
          j++;
          while (j < source.length && /\s/.test(source[j])) {
            if (source[j] === "\n") line++;
            j++;
          }
          if (source[j] === '"' || source[j] === "'") {
            const quote = source[j];
            j++;
            const startMod = j;
            while (j < source.length && source[j] !== quote) {
              if (source[j] === "\\") j += 2;
              else j++;
            }
            const mod = source.slice(startMod, j);
            j++; // skip quote
            while (j < source.length && /\s/.test(source[j])) j++;
            if (source[j] === ")") {
              results.push({
                module: mod,
                line,
                isModuleScope: braceDepth === 0,
              });
              i = j + 1;
              continue;
            }
          }
        }
      }
      i++;
    } else {
      i++;
    }
  }
  return results;
}

// Module table layers:
// L0 Composition: main.js
// L1 UI: core/panel.js, core/alignPanel.js, core/progressText.js
// L2 Features: features/*
// L3 Domain: workflow.js, helperStart.js, core/rpc.js, presetStore.js, timelineRange.js,
//            capabilityProbe.js, syncProbe.js, probes/*,
//            timeline/adjustmentLayer.js, timeline/alPlacement.js, timeline/alLibrary.js,
//            timeline/alProject.js, timeline/alSeedData.js, timeline/effects.js,
//            timeline/nativeSync.js, transform/*
// L4 Host: host/*
function getLayer(relPath) {
  const norm = relPath.replace(/\\/g, "/");
  if (norm === "main.js") return 0;
  if (norm === "core/panel.js" || norm === "core/alignPanel.js" || norm === "core/progressText.js") return 1;
  if (norm.startsWith("features/")) return 2;
  if (norm.startsWith("host/")) return 4;
  return 3; // domain
}

const allJsFiles = panelJsFiles(uxpDir);

test("every file named in KNOWN_EXCEPTIONS exists", () => {
  const referencedFiles = new Set();
  for (const e of KNOWN_EXCEPTIONS.executeTransaction) referencedFiles.add(e.file);
  for (const e of KNOWN_EXCEPTIONS.ticks) referencedFiles.add(e.file);
  for (const e of KNOWN_EXCEPTIONS.layerDirection) {
    referencedFiles.add(e.from);
    referencedFiles.add(e.to);
  }
  for (const e of KNOWN_EXCEPTIONS.premiereproModuleScope) referencedFiles.add(e.file);

  for (const rel of referencedFiles) {
    const full = path.join(uxpDir, rel);
    assert.ok(fs.existsSync(full), `File in KNOWN_EXCEPTIONS does not exist: ${rel}`);
  }
});

test("(a) executeTransaction( appears only in host/project.js (or known exceptions)", () => {
  const allowed = new Set(["host/project.js", ...KNOWN_EXCEPTIONS.executeTransaction.map((e) => e.file)]);
  const offenders = [];

  for (const file of allJsFiles) {
    const rel = path.relative(uxpDir, file).replace(/\\/g, "/");
    if (allowed.has(rel)) continue;

    const code = stripComments(fs.readFileSync(file, "utf8"));
    if (/executeTransaction\(/.test(code)) {
      offenders.push(rel);
    }
  }

  assert.deepEqual(offenders, [], `executeTransaction( found in unauthorized files: ${offenders.join(", ")}`);
});

test("(b) 254016000000 and TICKS_PER_SECOND = appear only in host/ticks.js (or known exceptions)", () => {
  const allowed = new Set(["host/ticks.js", ...KNOWN_EXCEPTIONS.ticks.map((e) => e.file)]);
  const offenders = [];

  for (const file of allJsFiles) {
    const rel = path.relative(uxpDir, file).replace(/\\/g, "/");
    if (allowed.has(rel)) continue;

    const code = stripComments(fs.readFileSync(file, "utf8"));
    if (/254016000000/.test(code) || /\bTICKS_PER_SECOND\s*=/.test(code)) {
      offenders.push(rel);
    }
  }

  assert.deepEqual(offenders, [], `Tick literals/assignments found in unauthorized files: ${offenders.join(", ")}`);
});

test("(c) layer direction: no module imports upward (lower layer requiring higher layer)", () => {
  const allowedExceptions = new Set(
    KNOWN_EXCEPTIONS.layerDirection.map((e) => `${e.from} -> ${e.to}`)
  );
  const violations = [];

  for (const file of allJsFiles) {
    const srcRel = path.relative(uxpDir, file).replace(/\\/g, "/");
    const srcLayer = getLayer(srcRel);
    const source = fs.readFileSync(file, "utf8");
    const requires = extractRequires(source);

    for (const req of requires) {
      if (!req.module.startsWith(".")) continue; // relative requires only

      let resolved = path.resolve(path.dirname(file), req.module);
      if (!fs.existsSync(resolved) && fs.existsSync(resolved + ".js")) {
        resolved = resolved + ".js";
      }
      const targetRel = path.relative(uxpDir, resolved).replace(/\\/g, "/");
      const targetLayer = getLayer(targetRel);

      if (srcLayer > targetLayer) {
        const edge = `${srcRel} -> ${targetRel}`;
        if (!allowedExceptions.has(edge)) {
          violations.push(`${edge} (L${srcLayer} -> L${targetLayer})`);
        }
      }
    }
  }

  assert.deepEqual(violations, [], `Upward layer imports detected: ${violations.join(", ")}`);
});

test("(d) require('premierepro') at module scope appears only in main.js (or known exceptions)", () => {
  const allowed = new Set(["main.js", ...KNOWN_EXCEPTIONS.premiereproModuleScope.map((e) => e.file)]);
  const offenders = [];

  for (const file of allJsFiles) {
    const rel = path.relative(uxpDir, file).replace(/\\/g, "/");
    if (allowed.has(rel)) continue;

    const source = fs.readFileSync(file, "utf8");
    const requires = extractRequires(source);

    for (const req of requires) {
      if (req.module === "premierepro" && req.isModuleScope) {
        offenders.push(`${rel}:${req.line}`);
      }
    }
  }

  assert.deepEqual(offenders, [], `require('premierepro') at module scope in unauthorized files: ${offenders.join(", ")}`);
});

test("(e) workflow.VERSION matches cutdeck/xml_bridge.py VERSION and helperStart.js has no version literal", () => {
  const workflowPath = path.join(uxpDir, "workflow.js");
  const xmlBridgePath = path.join(root, "cutdeck", "xml_bridge.py");
  const helperStartPath = path.join(uxpDir, "helperStart.js");

  const workflowSource = fs.readFileSync(workflowPath, "utf8");
  const xmlBridgeSource = fs.readFileSync(xmlBridgePath, "utf8");
  const helperStartSource = fs.readFileSync(helperStartPath, "utf8");

  const workflowMatch = workflowSource.match(/VERSION\s*=\s*["']([^"']+)["']/);
  assert.ok(workflowMatch, "VERSION constant not found in uxp/cutdeck/workflow.js");
  const workflowVersion = workflowMatch[1];

  const bridgeMatch = xmlBridgeSource.match(/VERSION\s*=\s*["']([^"']+)["']/);
  assert.ok(bridgeMatch, "VERSION constant not found in cutdeck/xml_bridge.py");
  const bridgeVersion = bridgeMatch[1];

  assert.equal(workflowVersion, bridgeVersion, `VERSION mismatch: workflow.js has "${workflowVersion}", xml_bridge.py has "${bridgeVersion}"`);

  assert.ok(
    !/["']cutdeck-xml-/.test(helperStartSource),
    "uxp/cutdeck/helperStart.js must not contain any 'cutdeck-xml-' literal; it must require opts.version from caller"
  );
});
