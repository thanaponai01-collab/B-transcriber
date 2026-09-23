/* Status line shown while the helper processes a cut job, shared by the CEP and UXP panels
 * (source of truth: panel/core/progressText.js; run scripts/sync_panel_core.py after editing). */

(function (global) {
  const SUFFIX = "cuts stay inside marked In/Out.";
  const FALLBACK = "Processing sequence in helper… Cuts stay inside marked In/Out.";

  // `job.progress` is {pct, stage} once xml_recut has announced a phase; absent before that
  // and for sync jobs. Anything malformed falls back to the static message rather than
  // showing "undefined… NaN%". `job.reference` names the audio being analyzed (e.g.
  // "A2 (interview.wav)") once the helper has checked it; older helpers never send it.
  function progressText(job) {
    const p = job && job.progress;
    if (!p || typeof p.stage !== "string" || !p.stage || !Number.isFinite(p.pct)) return FALLBACK;
    const pct = Math.max(0, Math.min(100, Math.round(p.pct)));
    const ref = typeof job.reference === "string" && job.reference ? `analyzing ${job.reference}; ` : "";
    return `${p.stage}… ${pct}% — ${ref}${SUFFIX}`;
  }

  const exportObj = { progressText, FALLBACK };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = exportObj;
  }
  if (global) {
    global.CutDeckProgressText = exportObj;
  }
})(typeof window !== "undefined" ? window : globalThis);
