// Re-downloads the pinned Adobe sources in reference/adobe/sources.json into reference/adobe/,
// then rebuilds the flat API index. Run after changing a pin:  node tools/adobe/refresh.mjs
// Needs npm, git and tar on PATH. Only text files are kept (no images), with Adobe's licenses.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const refDir = path.resolve(here, "..", "..", "reference", "adobe");
const sources = JSON.parse(fs.readFileSync(path.join(refDir, "sources.json"), "utf8"));
const keep = new Set(sources.keepExtensions);
const skipNames = new Set([".git", ".github", "node_modules", "package-lock.json", "yarn.lock"]);
const shell = process.platform === "win32";
const run = (cmd, args, cwd) => execFileSync(cmd, args, { cwd, stdio: ["ignore", "pipe", "inherit"], shell }).toString().trim();

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "adobe-ref-"));

function copyText(src, dst) {
  let n = 0;
  for (const e of fs.readdirSync(src, { withFileTypes: true })) {
    if (skipNames.has(e.name)) continue;
    const s = path.join(src, e.name);
    const d = path.join(dst, e.name);
    if (e.isDirectory()) n += copyText(s, d);
    else if (keep.has(path.extname(e.name).toLowerCase())) {
      fs.mkdirSync(dst, { recursive: true });
      fs.copyFileSync(s, d);
      n++;
    }
  }
  return n;
}

// Typings: npm pack each pinned version, keep the one .d.ts and its license.
const typingsDir = path.join(refDir, "typings");
fs.rmSync(typingsDir, { recursive: true, force: true });
fs.mkdirSync(typingsDir, { recursive: true });
for (const t of sources.typings) {
  const work = fs.mkdtempSync(path.join(tmp, "pkg-"));
  const tgz = run("npm", ["pack", `${t.package}@${t.version}`, "--silent"], work).split(/\r?\n/).pop();
  run("tar", ["-xzf", tgz], work);
  fs.copyFileSync(path.join(work, "package", t.file), path.join(typingsDir, t.saveAs));
  const lic = path.join(work, "package", "LICENSE");
  const licName = `LICENSE-${t.package.replace("@adobe/", "")}`;
  if (fs.existsSync(lic)) fs.copyFileSync(lic, path.join(typingsDir, licName));
  console.log(`typings  ${t.package}@${t.version} -> typings/${t.saveAs}`);
}

// Repos: fetch exactly the pinned commit, copy the text files under `from`.
for (const r of sources.repos) {
  const work = fs.mkdtempSync(path.join(tmp, "repo-"));
  run("git", ["init", "-q"], work);
  run("git", ["remote", "add", "origin", r.repo], work);
  run("git", ["fetch", "-q", "--depth", "1", "origin", r.sha], work);
  run("git", ["checkout", "-q", "FETCH_HEAD"], work);
  const dst = path.join(refDir, r.saveAs);
  fs.rmSync(dst, { recursive: true, force: true });
  const n = copyText(path.join(work, r.from), dst);
  for (const lic of sources.licenseFiles) {
    const p = path.join(work, lic);
    if (fs.existsSync(p)) fs.copyFileSync(p, path.join(dst, lic));
  }
  console.log(`repo     ${r.repo}@${r.sha.slice(0, 7)} -> ${r.saveAs}/ (${n} files)`);
}

fs.rmSync(tmp, { recursive: true, force: true });
await import("./build-index.mjs");
