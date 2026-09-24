// Builds reference/adobe/api/*.txt: one line per Adobe API member, fully qualified, so a
// plain grep answers "does X exist, on which class, with what signature, since when".
//   node tools/adobe/build-index.mjs
// Read by humans and agents; the API check (check-api.mjs) reads the .d.ts files directly.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const here = path.dirname(fileURLToPath(import.meta.url));
const ts = createRequire(import.meta.url)("typescript");
const refDir = path.resolve(here, "..", "..", "reference", "adobe");
const sources = JSON.parse(fs.readFileSync(path.join(refDir, "sources.json"), "utf8"));
const typingsFile = (pkg, version) => {
  const t = sources.typings.find((x) => x.package === pkg && (!version || x.version === version));
  return path.join(refDir, "typings", t.saveAs);
};

const oneLine = (s) => s.replace(/\s+/g, " ").trim();
const sinceOf = (node) => {
  const tag = ts.getJSDocTags(node).find((t) => t.tagName.text === "since");
  return tag ? oneLine(ts.getTextOfJSDocComment(tag.comment) || "") : "";
};
const docOf = (node) => {
  const docs = node.jsDoc || [];
  const text = docs.length ? oneLine(ts.getTextOfJSDocComment(docs[docs.length - 1].comment) || "") : "";
  const first = text.split(/(?<=\.)\s/)[0];
  return first.length > 140 ? `${first.slice(0, 137)}...` : first;
};
const nameOf = (node) => (node.name && (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name)) ? node.name.text : null);
const hasMod = (node, kind) => Boolean(node.modifiers && node.modifiers.some((m) => m.kind === kind));

// Signature without body: "(a: T, b?: U): R" for callables, ": T" for properties.
function sigOf(node, sf) {
  if (ts.isMethodSignature(node) || ts.isMethodDeclaration(node) || ts.isFunctionDeclaration(node) || ts.isConstructorDeclaration(node)) {
    const params = node.parameters.map((p) => oneLine(p.getText(sf))).join(", ");
    return `(${params})${node.type ? `: ${oneLine(node.type.getText(sf))}` : ""}`;
  }
  if ((ts.isPropertySignature(node) || ts.isPropertyDeclaration(node) || ts.isVariableDeclaration(node)) && node.type) {
    const t = oneLine(node.type.getText(sf));
    return `: ${t.length > 120 ? `${t.slice(0, 117)}...` : t}`;
  }
  return "";
}

// Walks modules, namespaces, classes, interfaces, type literals and enums; one entry per
// member with its dotted owner path. For premierepro, `FooStatic` type = static side of Foo.
function collect(file, flavor) {
  const sf = ts.createSourceFile(file, fs.readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true);
  const out = [];
  const join = (owner, n) => (owner ? `${owner}.${n}` : n);
  const emit = (owner, node, isStatic) => {
    const name = nameOf(node);
    if (!name) return;
    out.push({ owner, name, sig: sigOf(node, sf), since: sinceOf(node), doc: docOf(node),
      readonly: hasMod(node, ts.SyntaxKind.ReadonlyKeyword),
      isStatic: isStatic || hasMod(node, ts.SyntaxKind.StaticKeyword) });
  };
  const visit = (node, owner) => {
    if (ts.isModuleDeclaration(node)) {
      if (node.body) visit(node.body, join(owner, node.name.text));
    } else if (ts.isModuleBlock(node)) {
      ts.forEachChild(node, (c) => visit(c, owner));
    } else if (ts.isClassDeclaration(node) || ts.isInterfaceDeclaration(node)) {
      const n = join(owner, node.name ? node.name.text : "?");
      for (const m of node.members) emit(n, m, false);
    } else if (ts.isTypeAliasDeclaration(node) && ts.isTypeLiteralNode(node.type)) {
      let n = node.name.text;
      if (flavor === "premierepro" && n === "premierepro") return; // the module object: one key per class
      const isStatic = flavor === "premierepro" && n.endsWith("Static");
      if (isStatic) n = n.slice(0, -"Static".length);
      for (const m of node.type.members) emit(join(owner, n), m, isStatic);
    } else if (ts.isEnumDeclaration(node)) {
      const n = join(owner, node.name.text);
      for (const m of node.members) {
        out.push({ owner: n, name: m.name.getText(sf), sig: m.initializer ? ` = ${m.initializer.getText(sf)}` : "",
          since: sinceOf(m) || sinceOf(node), doc: docOf(m), enumMember: !m.initializer });
      }
    } else if (ts.isVariableStatement(node)) {
      for (const d of node.declarationList.declarations) emit(owner, d, false);
    } else if (ts.isFunctionDeclaration(node)) {
      emit(owner, node, false);
    }
  };
  ts.forEachChild(sf, (c) => visit(c, ""));
  return out;
}

const line = (e, extraTags = []) => {
  const tags = [];
  if (e.isStatic) tags.push("static");
  if (e.readonly) tags.push("readonly");
  if (e.since) tags.push(`since ${e.since}`);
  tags.push(...extraTags);
  if (e.enumMember) tags.push("enum value not in typings: probe it");
  return `${e.owner}.${e.name}${e.sig}${tags.length ? `  [${tags.join(", ")}]` : ""}${e.doc ? `  -- ${e.doc}` : ""}`;
};
const header = (title, lines) => [
  `# ${title}`,
  "# Generated by tools/adobe/build-index.mjs from reference/adobe/typings/. Do not edit; re-run it.",
  "# One line per member:  Owner.member<signature>  [tags]  -- first sentence of Adobe's doc comment",
  ...lines,
  "",
].join("\n");

const pv = sources.typings.find((t) => t.package === "@adobe/premierepro").version;
const uv = sources.typings.find((t) => t.package === "@adobe/cc-ext-uxp-types").version;

// Premiere, tagged against 26.2.1 (manifest minVersion) so 26.3+ APIs stand out.
const pproEntries = collect(typingsFile("@adobe/premierepro", pv), "premierepro");
const oldKeys = new Set(collect(typingsFile("@adobe/premierepro", "26.2.1"), "premierepro").map((e) => `${e.owner}.${e.name}`));
const pproLines = [...new Set(pproEntries.map((e) => line(e, oldKeys.has(`${e.owner}.${e.name}`) ? [] : ["NOT IN 26.2.1"])))]
  .sort((a, b) => a.localeCompare(b));

const uxpLines = [...new Set(collect(typingsFile("@adobe/cc-ext-uxp-types"), "uxp").map((e) => line(e)))]
  .sort((a, b) => a.localeCompare(b));

const apiDir = path.join(refDir, "api");
fs.mkdirSync(apiDir, { recursive: true });
fs.writeFileSync(path.join(apiDir, "premierepro.txt"), header(
  `Premiere Pro UXP API, @adobe/premierepro ${pv}. "NOT IN 26.2.1" = absent from the manifest-minVersion typings.`, pproLines));
fs.writeFileSync(path.join(apiDir, "uxp.txt"), header(
  `UXP platform API, @adobe/cc-ext-uxp-types ${uv}. These typings have gaps (e.g. storage.localFileSystem is documented but missing); also check docs/uxp-api/.`, uxpLines));
console.log(`index    api/premierepro.txt (${pproLines.length} members), api/uxp.txt (${uxpLines.length} members)`);
