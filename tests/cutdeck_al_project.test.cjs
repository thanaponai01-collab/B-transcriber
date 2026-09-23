/* timeline/alProject.js builds a .prproj holding one Adjustment Layer at an exact size.
   Provable off-host: the bytes are valid gzip, the XML has the requested size/name/rate in
   the one place each lives, identities are fresh, and no reference dangles. Whether Premiere
   imports it is NOT provable here — that is capabilityProbe.js probeCreateAdjustmentLayer. */
const test = require("node:test");
const assert = require("node:assert/strict");
const zlib = require("node:zlib");

const al = require("../uxp/cutdeck/timeline/alProject.js");
const SEED = require("../uxp/cutdeck/timeline/alSeedData.js");

const refs = (xml) => [...xml.matchAll(/Object(?:U)?Ref="([^"]+)"/g)].map((m) => m[1]);
const ids = (xml) => new Set([...xml.matchAll(/Object(?:U)?ID="([^"]+)"/g)].map((m) => m[1]));
const uids = (xml) => [...xml.matchAll(/ObjectUID="([^"]+)"/g)].map((m) => m[1]);

test("the seed is a one-AL project with no dangling references", () => {
  assert.equal((SEED.match(/<IsAdjustmentLayer>true/g) || []).length, 1);
  assert.equal((SEED.match(/<FrameRect>/g) || []).length, 1);
  const known = ids(SEED);
  assert.deepEqual(refs(SEED).filter((r) => !known.has(r)), []);
  assert.doesNotMatch(SEED, /[A-Z]:\\Me\\/, "no stale absolute project path from the source file");
});

test("builds the requested size, name and frame rate", () => {
  const { xml, name } = al.buildAdjustmentLayerProject({ width: 1080, height: 1920, ticksPerFrame: 8475667200 });
  assert.equal(name, "Adjustment Layer 1080x1920");
  assert.match(xml, /<FrameRect>0,0,1080,1920<\/FrameRect>/);
  assert.equal((xml.match(/<FrameRect>/g) || []).length, 1);
  assert.match(xml, /<ClipProjectItem [\s\S]*?<Name>Adjustment Layer 1080x1920<\/Name>/);
  assert.match(xml, /<MasterClip ObjectUID[\s\S]*?<Name>Adjustment Layer 1080x1920<\/Name>/);
  assert.match(xml, /<ClipName>Adjustment Layer 1080x1920<\/ClipName>/);
  assert.match(xml, /<MediaFrameRate>8475667200<\/MediaFrameRate>/);
  assert.match(xml, /<VideoStream ObjectID="[^"]+"[\s\S]*?<FrameRate>8475667200<\/FrameRate>/);
  // CutDeck's existing name matcher (pickBestCandidate) must find it for this sequence size.
  assert.match(name, new RegExp(`1080\\D{0,3}1920`));
  assert.doesNotMatch(name, new RegExp(`1920\\D{0,3}1080`));
});

test("leaves the seed's frame rate alone when none is given", () => {
  const { xml } = al.buildAdjustmentLayerProject({ width: 1920, height: 1080 });
  assert.match(xml, /<MediaFrameRate>10160640000<\/MediaFrameRate>/);
});

test("every ObjectUID is fresh per build and every reference still resolves", () => {
  const a = al.buildAdjustmentLayerProject({ width: 1920, height: 1080 }).xml;
  const b = al.buildAdjustmentLayerProject({ width: 1920, height: 1080 }).xml;
  const seedUids = new Set(uids(SEED));
  for (const u of uids(a)) assert.ok(!seedUids.has(u), `seed UID ${u} survived`);
  const shared = uids(a).filter((u) => new Set(uids(b)).has(u));
  assert.deepEqual(shared, []);
  const known = ids(a);
  assert.deepEqual(refs(a).filter((r) => !known.has(r)), []);
  assert.equal(uids(a).length, uids(SEED).length);
});

test("rejects sizes that can't be a real frame", () => {
  for (const [w, h] of [[0, 1080], [1920, -1], [1920.5, 1080], [NaN, 1080], [20000, 1080], ["1920", 1080]]) {
    assert.throws(() => al.buildAdjustmentLayerProject({ width: w, height: h }), /Cannot build/);
  }
  assert.throws(() => al.buildAdjustmentLayerProject({ width: 1920, height: 1080, ticksPerFrame: 1.5 }), /ticksPerFrame/);
});

test("refuses a seed that isn't exactly one AL", () => {
  const twoFlags = SEED.replace("</MasterClip>", "<IsAdjustmentLayer>true</IsAdjustmentLayer></MasterClip>");
  assert.throws(() => al.buildAdjustmentLayerProject({ width: 1920, height: 1080, seedXml: twoFlags }), /exactly one Adjustment Layer/);
  const noRect = SEED.replace(/<FrameRect>[^<]*<\/FrameRect>/, "");
  assert.throws(() => al.buildAdjustmentLayerProject({ width: 1920, height: 1080, seedXml: noRect }), /<FrameRect>/);
});

test("gzipStored round-trips through zlib, including multi-block input", () => {
  for (const size of [0, 5, 65535, 65536, 200001]) {
    const input = Uint8Array.from({ length: size }, (_, i) => (i * 31 + 7) & 0xff);
    const out = zlib.gunzipSync(Buffer.from(al.gzipStored(input)));
    assert.equal(out.length, size);
    assert.ok(Buffer.from(input).equals(out));
  }
});

test("the .prproj bytes gunzip back to the built XML", () => {
  let n = 0;
  const uuid = () => `00000000-0000-4000-8000-${String(++n).padStart(12, "0")}`;
  const { bytes, name } = al.buildAdjustmentLayerPrproj({ width: 3840, height: 2160, uuid });
  const xml = zlib.gunzipSync(Buffer.from(bytes)).toString("utf8");
  n = 0;
  assert.equal(xml, al.buildAdjustmentLayerProject({ width: 3840, height: 2160, uuid }).xml);
  assert.equal(name, "Adjustment Layer 3840x2160");
  assert.ok(xml.startsWith("<?xml"));
});

test("utf8Bytes matches Buffer for non-ASCII text", () => {
  const s = "Adjustment ปรับ × 🎬";
  assert.ok(Buffer.from(al.utf8Bytes(s)).equals(Buffer.from(s, "utf8")));
});
