/* Builds a one-item Premiere project (.prproj bytes) holding a Color Matte at an exact
   frame size, so CutDeck can import one for whatever sequence is active.
   Similar to alProject.js, but generates synthetic Color Matte media (FilePath 1129270354 = "CMTR")
   with ImporterPrefs for color and no IsAdjustmentLayer flag. */

const SEED_XML = require("./alSeedData.js");
const { gzipStored, utf8Bytes, crc32, MAX_SIDE, randomUuid, isSide, replaceOnce: alReplaceOnce } = require("./alProject.js");

const colorMatteName = (width, height) => `Color Matte ${width}x${height}`;

const replaceOnce = (xml, pattern, replacement, what) => alReplaceOnce(xml, pattern, replacement, what, "Color Matte");

function buildColorMatteProject({ width, height, ticksPerFrame, uuid = randomUuid, seedXml = SEED_XML }) {
  if (!isSide(width) || !isSide(height)) {
    throw new Error(`Cannot build a Color Matte of ${width}x${height}: sides must be whole numbers from 1 to ${MAX_SIDE}.`);
  }
  const name = colorMatteName(width, height);
  let xml = seedXml;

  // 1. Remove <IsAdjustmentLayer>true</IsAdjustmentLayer>
  xml = replaceOnce(xml, /<IsAdjustmentLayer>true<\/IsAdjustmentLayer>\s*/, "", "<IsAdjustmentLayer>");

  // 2. Change FilePath to Color Matte (1129270354 = 'CMTR')
  xml = replaceOnce(xml, /<FilePath>1112293707<\/FilePath>/, "<FilePath>1129270354</FilePath>", "FilePath");
  xml = replaceOnce(xml, /<ActualMediaFilePath>1112293707<\/ActualMediaFilePath>/, "<ActualMediaFilePath>1129270354</ActualMediaFilePath>", "ActualMediaFilePath");

  // 3. Inject ImporterPrefs for Color Matte into Media if missing
  if (!xml.includes("ImporterPrefs")) {
    xml = replaceOnce(
      xml,
      /(<Media [^>]*>[\s\S]*?<VideoStream [^>]*\/>)/,
      `$1\n\t\t<ImporterPrefs Encoding="base64" BinaryHash="5be7e6c2-37d0-2ee6-2984-d90a00000014">35CQAAEAAAA=\n\t\t</ImporterPrefs>`,
      "Media VideoStream"
    );
  }

  // 4. Update Title to Color Matte
  xml = replaceOnce(xml, /<Title>Black Video<\/Title>/, `<Title>${name}</Title>`, "<Title>");

  // 5. Update FrameRect and names
  xml = replaceOnce(xml, /<FrameRect>[^<]*<\/FrameRect>/, `<FrameRect>0,0,${width},${height}</FrameRect>`, "<FrameRect>");
  xml = replaceOnce(xml, /(<ClipProjectItem ObjectUID="[^"]+"[\s\S]*?<Name>)[^<]*(<\/Name>)/, `$1${name}$2`, "ClipProjectItem name");
  xml = replaceOnce(xml, /(<MasterClip ObjectUID="[^"]+"[\s\S]*?<Name>)[^<]*(<\/Name>)/, `$1${name}$2`, "MasterClip name");
  xml = replaceOnce(xml, /<ClipName>[^<]*<\/ClipName>/, `<ClipName>${name}</ClipName>`, "<ClipName>");

  if (ticksPerFrame !== undefined && ticksPerFrame !== null) {
    const tpf = Number(ticksPerFrame);
    if (!Number.isSafeInteger(tpf) || tpf <= 0) throw new Error(`Color Matte seed: bad ticksPerFrame ${ticksPerFrame}.`);
    xml = replaceOnce(xml, /(<VideoStream ObjectID="[^"]+"[\s\S]*?<FrameRate>)\d+(<\/FrameRate>)/, `$1${tpf}$2`, "VideoStream frame rate");
    xml = replaceOnce(xml, /<MediaFrameRate>\d+<\/MediaFrameRate>/, `<MediaFrameRate>${tpf}</MediaFrameRate>`, "<MediaFrameRate>");
  }

  // Fresh identity on every build
  const ids = new Set();
  for (const m of xml.matchAll(/ObjectUID="([0-9a-f-]{36})"/g)) ids.add(m[1]);
  for (const m of xml.matchAll(/<ClipID>([0-9a-f-]{36})<\/ClipID>/g)) ids.add(m[1]);
  for (const oldId of ids) xml = xml.split(oldId).join(uuid());

  return { xml, name };
}

function buildColorMattePrproj(options) {
  const { xml, name } = buildColorMatteProject(options);
  return { bytes: gzipStored(utf8Bytes(xml)), name };
}

module.exports = {
  buildColorMatteProject,
  buildColorMattePrproj,
  colorMatteName,
  gzipStored,
  utf8Bytes,
  crc32,
  MAX_SIDE,
};
