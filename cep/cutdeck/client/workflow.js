/* CutDeck CEP Workflow Bridge
 * Orchestrates ExtendScript host actions and helper RPC.
 */

(function (global) {
  const VERSION = "cutdeck-xml-1";

  function toCleanBigInt(val) {
    if (typeof val === "bigint") return val;
    const s = String(val || "0").trim();
    const integerPart = s.indexOf(".") !== -1 ? s.split(".")[0] : s;
    const digitsOnly = integerPart.replace(/[^0-9]/g, "");
    return BigInt(digitsOnly || "0");
  }

  function createWorkflow(evalScript) {
    async function capture() {
      const raw = await evalScript("getActiveSequenceInfo()");
      if (!raw) throw new Error("Premiere returned an empty response.");
      const info = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (info.error) throw new Error(info.error);

      const timebase = toCleanBigInt(info.ticks_per_frame);
      if (timebase <= 0n) throw new Error("Could not determine sequence frame rate / timebase.");

      // Align ticks cleanly to sequence frame grid so helper validation succeeds
      const rawIn = toCleanBigInt(info.in_ticks_raw);
      const inFrame = (rawIn + timebase / 2n) / timebase;
      const inTicks = (inFrame * timebase).toString();

      const rawOut = toCleanBigInt(info.out_ticks_raw);
      const outFrame = (rawOut + timebase / 2n) / timebase;
      const outTicks = (outFrame * timebase).toString();

      const rawEnd = toCleanBigInt(info.end_ticks_raw);
      const endFrame = (rawEnd + timebase / 2n) / timebase;
      const endTicks = (endFrame * timebase).toString();

      return {
        inSeconds: info.in_seconds,
        outSeconds: info.out_seconds,
        context: {
          project_id: info.project_id,
          sequence_id: info.sequence_id,
          sequence_name: info.sequence_name,
          in_ticks: inTicks,
          out_ticks: outTicks,
          end_ticks: endTicks,
          ticks_per_frame: timebase.toString(),
          audio_track_count: info.audio_track_count,
        }
      };
    }

    async function prepare(rpc, snapshot, options, save) {
      await rpc({ type: "hello", version: VERSION });
      const job = await rpc({ type: "prepare", ...snapshot.context, ...options });
      save(job);

      const safePath = JSON.stringify(job.source_path);
      const res = await evalScript("exportSequenceXML(" + safePath + ")");
      const expResult = typeof res === "string" ? JSON.parse(res) : res;
      if (expResult.error || !expResult.success) {
        throw new Error("Premiere could not export the sequence: " + (expResult.error || "export failed"));
      }

      job.exported = true;
      save(job);

      const started = await rpc({ type: "start", job_id: job.job_id });
      save({ ...job, ...started });
      return started;
    }

    async function importResult(job, previousAttempt, markAttempt) {
      const safePath = JSON.stringify(job.output_path);
      const safeName = JSON.stringify(job.result_name);

      if (previousAttempt) {
        const chk = await evalScript("setActiveSequenceByName(" + safeName + ")");
        const chkRes = typeof chk === "string" ? JSON.parse(chk) : chk;
        if (chkRes && chkRes.success) return chkRes;
        throw new Error("A previous import could not be confirmed. Check the Project panel before importing again. Result: " + job.output_path);
      }

      if (typeof markAttempt === "function") {
        markAttempt();
      }

      const res = await evalScript("importResultXML(" + safePath + ", " + safeName + ")");
      const impResult = typeof res === "string" ? JSON.parse(res) : res;
      if (impResult.error) {
        throw new Error(impResult.error);
      }
      return impResult;
    }

    return { VERSION, capture, prepare, importResult };
  }

  const exportObj = { VERSION, createWorkflow };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = exportObj;
  }
  if (global) {
    global.CutDeckWorkflow = exportObj;
  }
})(typeof window !== "undefined" ? window : globalThis);
