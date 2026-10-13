/* Reads the whole timeline into plain data: every clip item per track with its ticks, plus the
   media file behind it. Read-only; shared by Sync, Rough Cut, the cut probes and the driver. */

const { toTicks } = require("./ticks.js");
const { getTrackClipItems } = require("./trackItems.js");

async function listClips(ppro, seq, kind, { end = true, inPoint = true } = {}) {
  const video = kind === "video";
  const count = await (video ? seq.getVideoTrackCount() : seq.getAudioTrackCount());
  const clips = [];
  for (let t = 0; t < count; t++) {
    const track = await (video ? seq.getVideoTrack(t) : seq.getAudioTrack(t));
    const items = track ? await getTrackClipItems(track, ppro) : [];
    if (!items.length) continue;
    const trackClips = await Promise.all(items.map(async (item) => {
      const [startTick, endTick, inPointTick] = await Promise.all([
        item.getStartTime(),
        end ? item.getEndTime() : null,
        inPoint ? item.getInPoint() : null,
      ]);
      return {
        item,
        kind,
        track: t,
        start: toTicks(startTick),
        end: end ? toTicks(endTick) : undefined,
        inPoint: inPoint ? toTicks(inPointTick) : undefined,
      };
    }));
    clips.push(...trackClips);
  }
  return { count, clips };
}

async function mediaPath(ppro, item) {
  const projectItem = typeof item.getProjectItem === "function" ? await item.getProjectItem() : null;
  const clip = ppro && ppro.ClipProjectItem && ppro.ClipProjectItem.cast ? ppro.ClipProjectItem.cast(projectItem) : projectItem;
  return clip && typeof clip.getMediaFilePath === "function" ? (await clip.getMediaFilePath()) || null : null;
}

async function mediaInfo(ppro, item) {
  const projectItem = typeof item.getProjectItem === "function" ? await item.getProjectItem() : null;
  const clip = ppro && ppro.ClipProjectItem && ppro.ClipProjectItem.cast ? ppro.ClipProjectItem.cast(projectItem) : projectItem;
  const path = clip && typeof clip.getMediaFilePath === "function" ? (await clip.getMediaFilePath()) || null : null;
  const targetItem = clip || projectItem;
  let colorLabel = null;
  if (typeof item.getColorLabelIndex === "function") {
    try { colorLabel = await item.getColorLabelIndex(); } catch (_) {}
  }
  if (colorLabel === null && targetItem && typeof targetItem.getColorLabelIndex === "function") {
    try { colorLabel = await targetItem.getColorLabelIndex(); } catch (_) {}
  }
  if (colorLabel === null && projectItem && typeof projectItem.getColorLabelIndex === "function") {
    try { colorLabel = await projectItem.getColorLabelIndex(); } catch (_) {}
  }
  return { projectItem: projectItem || clip, path, colorLabel };
}

/* Every clip item on the sequence, each with the file behind it (null when it has none).
   `paths: false` skips the file lookup (2 host calls per clip) for reads that only need
   positions — c.path is then undefined; `end: false` / `inPoint: false` likewise skip those
   (1 call each per clip). */
async function readSequence(ppro, seq, { paths = true, end = true, inPoint = true } = {}) {
  const [video, audio] = await Promise.all([
    listClips(ppro, seq, "video", { end, inPoint }),
    listClips(ppro, seq, "audio", { end, inPoint }),
  ]);
  if (paths) {
    const allClips = [...video.clips, ...audio.clips];
    const cache = new Map();
    for (const c of allClips) {
      try {
        let info = cache.get(c.item);
        if (!info) {
          info = await mediaInfo(ppro, c.item);
          cache.set(c.item, info);
        }
        c.path = info.path;
        c.projectItem = info.projectItem;
        c.colorLabel = info.colorLabel;
      } catch (_) {
        c.path = null;
        c.projectItem = null;
        c.colorLabel = null;
      }
    }
    cache.clear();
  }
  return { videoTracks: video.count, audioTracks: audio.count, video: video.clips, audio: audio.clips };
}

module.exports = { readSequence, mediaPath };
