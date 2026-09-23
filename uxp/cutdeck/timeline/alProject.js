/* Builds a one-item Premiere project (.prproj bytes) holding an Adjustment Layer at an exact
   frame size, so CutDeck can import one for whatever sequence is active.

   Why a generated project: the UXP API has no createAdjustmentLayer / synthetic-media call
   (checked against @adobe/premierepro@26.2.1's premierepro.d.ts), but Project.importFiles
   accepts a .prproj, and a .prproj is gzipped XML in which an AL's frame size lives in exactly
   one <FrameRect>. So: take the embedded one-AL seed (alSeedData.js), patch size, names, frame
   rate and every ObjectUID, gzip it, and let Premiere import it.

   No host calls and no DOM: pure string/byte work, testable in node. Whether Premiere accepts
   the result is what capabilityProbe.js probeCreateAdjustmentLayer asks the real host. */

const SEED_XML = require("./alSeedData.js");

// Premiere's own frame-size ceiling is 16384 on either side; anything outside is a bad read.
const MAX_SIDE = 16384;

const adjustmentLayerName = (width, height) => `Adjustment Layer ${width}x${height}`;

function randomUuid() {
  const hex = [];
  for (let i = 0; i < 16; i++) hex.push(Math.floor(Math.random() * 256));
  hex[6] = (hex[6] & 0x0f) | 0x40; // version 4
  hex[8] = (hex[8] & 0x3f) | 0x80; // RFC 4122 variant
  const h = hex.map((b) => b.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

const isSide = (n) => Number.isInteger(n) && n > 0 && n <= MAX_SIDE;

// Replaces exactly one match or throws: a seed that doesn't have the shape we patch must fail
// loudly here, not import a silently-wrong AL.
function replaceOnce(xml, pattern, replacement, what) {
  const count = (xml.match(new RegExp(pattern.source, "g")) || []).length;
  if (count !== 1) throw new Error(`AL seed: expected exactly one ${what}, found ${count}.`);
  return xml.replace(pattern, replacement);
}

/* Returns { xml, name }. `ticksPerFrame` (optional) sets the AL's media frame rate to the
   sequence's; the seed is 25 fps, and an AL plays at any rate, so it's cosmetic, not required. */
function buildAdjustmentLayerProject({ width, height, ticksPerFrame, uuid = randomUuid, seedXml = SEED_XML }) {
  if (!isSide(width) || !isSide(height)) {
    throw new Error(`Cannot build an Adjustment Layer of ${width}x${height}: sides must be whole numbers from 1 to ${MAX_SIDE}.`);
  }
  const name = adjustmentLayerName(width, height);
  let xml = seedXml;

  const alFlags = (xml.match(/<IsAdjustmentLayer>true<\/IsAdjustmentLayer>/g) || []).length;
  if (alFlags !== 1) throw new Error(`AL seed: expected exactly one Adjustment Layer, found ${alFlags}.`);

  xml = replaceOnce(xml, /<FrameRect>[^<]*<\/FrameRect>/, `<FrameRect>0,0,${width},${height}</FrameRect>`, "<FrameRect>");
  xml = replaceOnce(xml, /(<ClipProjectItem ObjectUID="[^"]+"[\s\S]*?<Name>)[^<]*(<\/Name>)/, `$1${name}$2`, "ClipProjectItem name");
  xml = replaceOnce(xml, /(<MasterClip ObjectUID="[^"]+"[\s\S]*?<Name>)[^<]*(<\/Name>)/, `$1${name}$2`, "MasterClip name");
  xml = replaceOnce(xml, /<ClipName>[^<]*<\/ClipName>/, `<ClipName>${name}</ClipName>`, "<ClipName>");

  if (ticksPerFrame !== undefined && ticksPerFrame !== null) {
    const tpf = Number(ticksPerFrame);
    if (!Number.isSafeInteger(tpf) || tpf <= 0) throw new Error(`AL seed: bad ticksPerFrame ${ticksPerFrame}.`);
    xml = replaceOnce(xml, /(<VideoStream ObjectID="[^"]+"[\s\S]*?<FrameRate>)\d+(<\/FrameRate>)/, `$1${tpf}$2`, "VideoStream frame rate");
    xml = replaceOnce(xml, /<MediaFrameRate>\d+<\/MediaFrameRate>/, `<MediaFrameRate>${tpf}</MediaFrameRate>`, "<MediaFrameRate>");
  }

  // Fresh identity on every build: importing a second AL whose ObjectUIDs match one already in
  // the project could be merged or skipped by Premiere rather than added.
  const ids = new Set();
  for (const m of xml.matchAll(/ObjectUID="([0-9a-f-]{36})"/g)) ids.add(m[1]);
  for (const m of xml.matchAll(/<ClipID>([0-9a-f-]{36})<\/ClipID>/g)) ids.add(m[1]);
  for (const oldId of ids) xml = xml.split(oldId).join(uuid());

  return { xml, name };
}

function utf8Bytes(text) {
  if (typeof TextEncoder === "function") return new TextEncoder().encode(text);
  const out = [];
  for (const ch of text) {
    let c = ch.codePointAt(0);
    if (c < 0x80) out.push(c);
    else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
    else if (c < 0x10000) out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    else out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
  }
  return Uint8Array.from(out);
}

let crcTable = null;
function crc32(bytes) {
  if (!crcTable) {
    crcTable = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      crcTable[n] = c >>> 0;
    }
  }
  let crc = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) crc = crcTable[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

/* A valid gzip stream using deflate "stored" (uncompressed) blocks. UXP has no zlib, and a
   .prproj is ~80 KB either way, so compression buys nothing; validity is all that matters. */
function gzipStored(bytes) {
  const BLOCK = 0xffff;
  const blocks = Math.max(1, Math.ceil(bytes.length / BLOCK));
  const out = new Uint8Array(10 + blocks * 5 + bytes.length + 8);
  out.set([0x1f, 0x8b, 0x08, 0, 0, 0, 0, 0, 0, 0xff], 0);
  let o = 10;
  for (let b = 0; b < blocks; b++) {
    const start = b * BLOCK;
    const len = Math.min(BLOCK, bytes.length - start);
    out[o++] = b === blocks - 1 ? 1 : 0;
    out[o++] = len & 0xff; out[o++] = len >>> 8;
    out[o++] = ~len & 0xff; out[o++] = (~len >>> 8) & 0xff;
    out.set(bytes.subarray(start, start + len), o);
    o += len;
  }
  const crc = crc32(bytes);
  const size = bytes.length >>> 0;
  out.set([crc & 0xff, (crc >>> 8) & 0xff, (crc >>> 16) & 0xff, crc >>> 24,
    size & 0xff, (size >>> 8) & 0xff, (size >>> 16) & 0xff, size >>> 24], o);
  return out;
}

/* The .prproj file's bytes for an AL of this size: build + encode + gzip. */
function buildAdjustmentLayerPrproj(options) {
  const { xml, name } = buildAdjustmentLayerProject(options);
  return { bytes: gzipStored(utf8Bytes(xml)), name };
}

module.exports = {
  buildAdjustmentLayerProject,
  buildAdjustmentLayerPrproj,
  adjustmentLayerName,
  gzipStored,
  utf8Bytes,
  crc32,
  MAX_SIDE,
};
