// Status text shown while the helper processes a cut job.

const FALLBACK = "Analyzing the full sequence with your current preset. Cuts will stay inside the captured In/Out range.\nThis can take several minutes.";

// `job.progress` is {pct, stage} once xml_recut has announced a phase; absent before that.
// Anything malformed falls back to the static message rather than showing "undefined… NaN%".
function progressText(job) {
  const p = job && job.progress;
  if (!p || typeof p.stage !== "string" || !p.stage || !Number.isFinite(p.pct)) return FALLBACK;
  const pct = Math.max(0, Math.min(100, Math.round(p.pct)));
  return `${p.stage}… ${pct}%\nCuts will stay inside the captured In/Out range.`;
}

module.exports = { progressText, FALLBACK };
