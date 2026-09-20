/**
 * CutDeck ExtendScript Host Bridge for Premiere Pro
 */

function _safeJSON(obj) {
  try {
    return JSON.stringify(obj);
  } catch (e) {
    return '{"error":"Failed to serialize response: ' + String(e) + '"}';
  }
}

function _parseTimeToTicksAndSeconds(val) {
  if (!val && val !== 0) return { ticks: "0", seconds: 0 };

  if (typeof val === "object" && val !== null) {
    if (val.ticks !== undefined) {
      return {
        ticks: String(val.ticks).split(".")[0],
        seconds: val.seconds !== undefined ? Number(val.seconds) : 0
      };
    }
  }

  var s = String(val).replace(/^\s+|\s+$/g, "");
  var num = parseFloat(s);
  if (isNaN(num)) return { ticks: "0", seconds: 0 };

  // Premiere ticks are 254,016,000,000 per second.
  // Any sequence duration or mark > 1,000,000 is definitively in ticks.
  if (num > 1000000) {
    var tickStr = s.indexOf(".") !== -1 ? s.split(".")[0] : s;
    var t = new Time();
    t.ticks = tickStr;
    return {
      ticks: tickStr,
      seconds: t.seconds !== undefined ? Number(t.seconds) : (num / 254016000000)
    };
  } else {
    var t2 = new Time();
    t2.seconds = num;
    return {
      ticks: String(t2.ticks).split(".")[0],
      seconds: num
    };
  }
}

function getActiveSequenceInfo() {
  var project = app.project;
  if (!project) {
    return _safeJSON({ error: "Open a Premiere project first." });
  }

  var seq = project.activeSequence;
  if (!seq) {
    return _safeJSON({ error: "Open a sequence and set timeline In/Out marks." });
  }

  var inParsed = _parseTimeToTicksAndSeconds(seq.getInPoint());
  var outParsed = _parseTimeToTicksAndSeconds(seq.getOutPoint());
  var endParsed = _parseTimeToTicksAndSeconds(seq.end);

  // Check only the last clip on each track to find latest clip end (clips are chronological in Premiere)
  var maxEndTicks = 0;
  try {
    if (seq.videoTracks) {
      for (var v = 0; v < seq.videoTracks.numTracks; v++) {
        var vt = seq.videoTracks[v];
        var vCount = vt.clips.numItems;
        if (vCount > 0) {
          var ve = _parseTimeToTicksAndSeconds(vt.clips[vCount - 1].end);
          var ven = parseFloat(ve.ticks);
          if (ven > maxEndTicks) maxEndTicks = ven;
        }
      }
    }
    if (seq.audioTracks) {
      for (var a = 0; a < seq.audioTracks.numTracks; a++) {
        var at = seq.audioTracks[a];
        var aCount = at.clips.numItems;
        if (aCount > 0) {
          var ae = _parseTimeToTicksAndSeconds(at.clips[aCount - 1].end);
          var aen = parseFloat(ae.ticks);
          if (aen > maxEndTicks) maxEndTicks = aen;
        }
      }
    }
  } catch (_) {}

  if (maxEndTicks > 0) {
    endParsed.ticks = String(maxEndTicks).split(".")[0];
    var tEnd = new Time();
    tEnd.ticks = endParsed.ticks;
    endParsed.seconds = tEnd.seconds !== undefined ? Number(tEnd.seconds) : (maxEndTicks / 254016000000);
  }

  // If Out point is at or past the end of the footage, clamp to sequence end
  if (parseFloat(outParsed.ticks) > parseFloat(endParsed.ticks) && parseFloat(endParsed.ticks) > 0) {
    outParsed.ticks = endParsed.ticks;
    outParsed.seconds = endParsed.seconds;
  }

  // If no In/Out marks are set or if Out <= In, default cleanly to the entire sequence
  if (inParsed.seconds < 0 || outParsed.seconds <= inParsed.seconds) {
    inParsed.seconds = 0;
    inParsed.ticks = "0";
    outParsed.seconds = endParsed.seconds;
    outParsed.ticks = endParsed.ticks;
  }

  var timebaseStr = "0";
  if (seq.timebase) {
    timebaseStr = String(seq.timebase).split(".")[0];
  }
  if (timebaseStr === "0") {
    try {
      var settings = seq.getSettings();
      if (settings && settings.videoFrameRate && settings.videoFrameRate.ticks) {
        timebaseStr = String(settings.videoFrameRate.ticks).split(".")[0];
      }
    } catch (_) {}
  }

  var audioTrackCount = (seq.audioTracks && seq.audioTracks.numTracks !== undefined) ? seq.audioTracks.numTracks : 0;
  var projId = project.documentID ? String(project.documentID) : (project.path ? String(project.path) : "project");

  return _safeJSON({
    project_id: projId,
    sequence_id: String(seq.sequenceID),
    sequence_name: String(seq.name),
    in_seconds: inParsed.seconds,
    out_seconds: outParsed.seconds,
    end_seconds: endParsed.seconds,
    in_ticks_raw: inParsed.ticks,
    out_ticks_raw: outParsed.ticks,
    end_ticks_raw: endParsed.ticks,
    ticks_per_frame: timebaseStr,
    audio_track_count: audioTrackCount
  });
}

function exportSequenceXML(outputPath) {
  var project = app.project;
  if (!project) {
    return _safeJSON({ error: "No active project." });
  }

  var seq = project.activeSequence;
  if (!seq) {
    return _safeJSON({ error: "No active sequence." });
  }

  if (typeof seq.exportAsFinalCutProXML !== "function") {
    return _safeJSON({ error: "This Premiere version does not support XML export via ExtendScript." });
  }

  // suppressUI = 1 (do not show file prompt)
  var ok = seq.exportAsFinalCutProXML(outputPath, 1);
  if (!ok) {
    return _safeJSON({ error: "Premiere failed to export the sequence XML." });
  }

  return _safeJSON({ success: true });
}

function importResultXML(outputPath, resultName) {
  var project = app.project;
  if (!project) {
    return _safeJSON({ error: "Return to the original project, then resume this job." });
  }

  var beforeIds = {};
  for (var i = 0; i < project.sequences.numSequences; i++) {
    beforeIds[String(project.sequences[i].sequenceID)] = true;
  }

  // importFiles(filePaths, suppressUI, targetBin, importAsNumberedStills)
  var ok = project.importFiles([outputPath], true, project.rootItem, false);
  if (!ok) {
    return _safeJSON({ error: "Premiere did not confirm the XML import: " + outputPath });
  }

  var targetSeq = null;
  // 1. Look for newly added sequence matching resultName
  for (var j = 0; j < project.sequences.numSequences; j++) {
    var s = project.sequences[j];
    if (!beforeIds[String(s.sequenceID)] && s.name === resultName) {
      targetSeq = s;
      break;
    }
  }

  // 2. Fallback: search by resultName if diff failed
  if (!targetSeq) {
    for (var k = 0; k < project.sequences.numSequences; k++) {
      if (project.sequences[k].name === resultName) {
        targetSeq = project.sequences[k];
        break;
      }
    }
  }

  if (!targetSeq) {
    return _safeJSON({ error: "Could not identify the imported sequence: " + resultName });
  }

  project.activeSequence = targetSeq;
  if (project.openSequence) {
    try { project.openSequence(targetSeq.sequenceID); } catch (_) {}
  }

  return _safeJSON({ success: true, sequenceID: String(targetSeq.sequenceID), name: String(targetSeq.name) });
}

function setActiveSequenceByName(seqName) {
  var project = app.project;
  if (!project) {
    return _safeJSON({ error: "No active project." });
  }

  for (var i = 0; i < project.sequences.numSequences; i++) {
    var seq = project.sequences[i];
    if (seq.name === seqName) {
      project.activeSequence = seq;
      if (project.openSequence) {
        try { project.openSequence(seq.sequenceID); } catch (_) {}
      }
      return _safeJSON({ success: true, sequenceID: String(seq.sequenceID), name: String(seq.name) });
    }
  }

  return _safeJSON({ error: "Sequence not found: " + seqName });
}
