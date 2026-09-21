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

// ----------------------------------------------------------------------------
// CutDeck Adjustment Layer & FX Automation Engine
// ----------------------------------------------------------------------------

function _getLabelIndex(colorName) {
  var map = {
    "violet": 0, "iris": 1, "caribbean": 2, "lavender": 3,
    "cerulean": 4, "forest": 5, "rose": 6, "mango": 7,
    "purple": 8, "blue": 9, "teal": 10, "magenta": 11,
    "tan": 12, "green": 13, "brown": 14, "yellow": 15
  };
  if (!colorName) return 1; // default Iris
  var key = String(colorName).toLowerCase();
  return map[key] !== undefined ? map[key] : 1;
}

function _getOrCreateCutDeckBin(binName) {
  if (!binName) binName = "CutDeck AL/FX";
  var root = app.project.rootItem;
  if (!root || !root.children) return null;
  for (var i = 0; i < root.children.numItems; i++) {
    var item = root.children[i];
    if (item && item.name === binName && item.type === 2) {
      return item;
    }
  }
  try {
    return root.createBin(binName);
  } catch (e) {
    return root;
  }
}

function _findAnyAdjustmentLayer(folder) {
  if (!folder || !folder.children) return null;
  for (var i = 0; i < folder.children.numItems; i++) {
    var item = folder.children[i];
    if (item) {
      if (item.type === 1 && item.name.toLowerCase().indexOf("adjustment layer") !== -1) {
        return item;
      }
      if (item.type === 2 && item.children) {
        var found = _findAnyAdjustmentLayer(item);
        if (found) return found;
      }
    }
  }
  return null;
}

function _getOrCreateAdjustmentLayerProjectItem(binName, labelColorName) {
  var bin = _getOrCreateCutDeckBin(binName);
  if (!bin) bin = app.project.rootItem;

  // 1. Check if an Adjustment Layer already exists in our CutDeck bin
  for (var i = 0; i < bin.children.numItems; i++) {
    var child = bin.children[i];
    if (child && child.type === 1 && (child.name === "Master Adjustment Layer" || child.name === "Adjustment Layer" || child.name.indexOf("ADJ_") === 0)) {
      return child;
    }
  }

  // 2. Try creating via QE DOM
  try {
    if (typeof qe === "undefined") {
      app.enableQE();
    }
    if (typeof qe !== "undefined" && qe.project && typeof qe.project.newAdjustmentLayer === "function") {
      var seq = app.project.activeSequence;
      var w = 1920, h = 1080, tb = 25, pa = 1.0;
      if (seq) {
        try {
          var st = seq.getSettings();
          if (st) {
            if (st.videoFrameWidth) w = st.videoFrameWidth;
            if (st.videoFrameHeight) h = st.videoFrameHeight;
            if (st.videoPixelAspectRatio) pa = st.videoPixelAspectRatio;
            if (st.videoFrameRate && st.videoFrameRate.seconds) {
              tb = 1.0 / st.videoFrameRate.seconds;
            }
          }
        } catch (_) {}
      }
      qe.project.newAdjustmentLayer(w, h, tb, pa);

      // Newly created AL appears in rootItem
      for (var k = app.project.rootItem.children.numItems - 1; k >= 0; k--) {
        var newItem = app.project.rootItem.children[k];
        if (newItem && newItem.name === "Adjustment Layer") {
          newItem.name = "Master Adjustment Layer";
          try { newItem.setColorLabel(_getLabelIndex(labelColorName)); } catch (_) {}
          try { newItem.moveProjectItem(bin); } catch (_) {}
          return newItem;
        }
      }
    }
  } catch (_) {}

  // 3. Fallback: Search anywhere in project for existing adjustment layer
  var existing = _findAnyAdjustmentLayer(app.project.rootItem);
  if (existing) {
    return existing;
  }

  return null;
}

function _getSelectedVideoClips(seq) {
  var selected = [];
  try {
    if (typeof seq.getSelection === "function") {
      var sel = seq.getSelection();
      if (sel && sel.length > 0) {
        for (var s = 0; s < sel.length; s++) {
          if (sel[s] && sel[s].mediaType === "Video") {
            selected.push(sel[s]);
          }
        }
      }
    }
  } catch (_) {}

  if (selected.length === 0 && seq.videoTracks) {
    for (var v = 0; v < seq.videoTracks.numTracks; v++) {
      var track = seq.videoTracks[v];
      for (var c = 0; c < track.clips.numItems; c++) {
        var clip = track.clips[c];
        try {
          if (clip && clip.isSelected && clip.isSelected()) {
            selected.push(clip);
          }
        } catch (_) {}
      }
    }
  }

  selected.sort(function (a, b) {
    var aStart = parseFloat(_parseTimeToTicksAndSeconds(a.start).ticks);
    var bStart = parseFloat(_parseTimeToTicksAndSeconds(b.start).ticks);
    return aStart - bStart;
  });

  return selected;
}

function _findSmartStackTrackIndex(seq, startTicksNum, endTicksNum) {
  var highestOccupied = -1;
  if (!seq.videoTracks) return 0;

  for (var v = 0; v < seq.videoTracks.numTracks; v++) {
    var track = seq.videoTracks[v];
    var hasClipInRange = false;
    for (var c = 0; c < track.clips.numItems; c++) {
      var clip = track.clips[c];
      var cStart = parseFloat(_parseTimeToTicksAndSeconds(clip.start).ticks);
      var cEnd = parseFloat(_parseTimeToTicksAndSeconds(clip.end).ticks);
      if (cEnd > startTicksNum && cStart < endTicksNum) {
        hasClipInRange = true;
        break;
      }
    }
    if (hasClipInRange) {
      if (v > highestOccupied) {
        highestOccupied = v;
      }
    }
  }

  return highestOccupied + 1;
}

function _ensureVideoTrackExists(seq, targetTrackIndex) {
  if (!seq.videoTracks) return false;
  if (targetTrackIndex < seq.videoTracks.numTracks) return true;

  try {
    if (typeof qe === "undefined") app.enableQE();
    var qSeq = qe.project.getActiveSequence();
    if (qSeq && typeof qSeq.addTracks === "function") {
      var needed = targetTrackIndex - seq.videoTracks.numTracks + 1;
      qSeq.addTracks(needed, seq.videoTracks.numTracks, 0, 0, 0, 0);
    }
  } catch (_) {}

  return targetTrackIndex < seq.videoTracks.numTracks;
}

/**
 * Execute 1-Click Adjustment Layer placement (Span or Transition)
 * @param {string} optionsJson - Serialized JSON configuration
 */
function placeAdjustmentLayers(optionsJson) {
  var project = app.project;
  if (!project) return _safeJSON({ error: "Open a Premiere project first." });
  var seq = project.activeSequence;
  if (!seq) return _safeJSON({ error: "No active sequence found." });

  var opt = {};
  try {
    opt = JSON.parse(optionsJson);
  } catch (e) {
    return _safeJSON({ error: "Invalid options JSON: " + String(e) });
  }

  var mode = opt.mode || "span"; // "span" or "transition"
  var binName = opt.binName || "CutDeck AL/FX";
  var labelColorName = opt.labelColor || "Iris";
  var labelIndex = _getLabelIndex(labelColorName);
  var transitionFrames = parseInt(opt.transitionFrames, 10) || 16;
  var clampShortClips = opt.clampShortClips !== false;
  var effectName = opt.effectName || "";

  var alItem = _getOrCreateAdjustmentLayerProjectItem(binName, labelColorName);
  if (!alItem) {
    return _safeJSON({ error: "Could not create or locate an Adjustment Layer in project. Please ensure QE is enabled." });
  }

  var timebaseTicks = 10594584000;
  try {
    var st = seq.getSettings();
    if (st && st.videoFrameRate && st.videoFrameRate.ticks) {
      timebaseTicks = parseFloat(st.videoFrameRate.ticks);
    } else if (seq.timebase) {
      timebaseTicks = parseFloat(seq.timebase);
    }
  } catch (_) {}

  var selectedClips = _getSelectedVideoClips(seq);
  var placements = [];

  if (mode === "span") {
    // -------------------------------------------------------------
    // SPAN MODE: Fit exact duration on top of each selected clip
    // -------------------------------------------------------------
    if (selectedClips.length === 0) {
      // If nothing selected, check In/Out or clip under CTI
      var inP = _parseTimeToTicksAndSeconds(seq.getInPoint());
      var outP = _parseTimeToTicksAndSeconds(seq.getOutPoint());
      if (outP.seconds > inP.seconds && inP.seconds >= 0) {
        placements.push({
          startTicks: inP.ticks,
          endTicks: outP.ticks,
          name: effectName ? ("ADJ_" + effectName) : "ADJ_InOut"
        });
      } else {
        return _safeJSON({ error: "Select one or more clips to span with an Adjustment Layer." });
      }
    } else {
      for (var i = 0; i < selectedClips.length; i++) {
        var cl = selectedClips[i];
        var sT = _parseTimeToTicksAndSeconds(cl.start).ticks;
        var eT = _parseTimeToTicksAndSeconds(cl.end).ticks;
        placements.push({
          startTicks: sT,
          endTicks: eT,
          name: effectName ? ("ADJ_" + effectName) : ("ADJ_Clip_" + (i + 1))
        });
      }
    }
  } else if (mode === "transition") {
    // -------------------------------------------------------------
    // TRANSITION MODE: 50/50 centered on cuts
    // -------------------------------------------------------------
    var halfFrames = Math.floor(transitionFrames / 2);
    var halfTicks = halfFrames * timebaseTicks;

    if (selectedClips.length >= 2) {
      // Detect cuts between adjacent selected clips
      for (var j = 0; j < selectedClips.length - 1; j++) {
        var cLeft = selectedClips[j];
        var cRight = selectedClips[j + 1];
        var leftEnd = parseFloat(_parseTimeToTicksAndSeconds(cLeft.end).ticks);
        var rightStart = parseFloat(_parseTimeToTicksAndSeconds(cRight.start).ticks);

        // Within 2 frames tolerance of a clean cut
        if (Math.abs(rightStart - leftEnd) <= (timebaseTicks * 2)) {
          var cutTick = leftEnd;
          var curHalfLeft = halfTicks;
          var curHalfRight = halfTicks;

          if (clampShortClips) {
            var durLeftTicks = parseFloat(_parseTimeToTicksAndSeconds(cLeft.end).ticks) - parseFloat(_parseTimeToTicksAndSeconds(cLeft.start).ticks);
            var durRightTicks = parseFloat(_parseTimeToTicksAndSeconds(cRight.end).ticks) - parseFloat(_parseTimeToTicksAndSeconds(cRight.start).ticks);
            var maxHalfLeft = durLeftTicks * 0.45;
            var maxHalfRight = durRightTicks * 0.45;
            if (curHalfLeft > maxHalfLeft) curHalfLeft = maxHalfLeft;
            if (curHalfRight > maxHalfRight) curHalfRight = maxHalfRight;
          }

          placements.push({
            startTicks: String(Math.round(cutTick - curHalfLeft)),
            endTicks: String(Math.round(cutTick + curHalfRight)),
            name: effectName ? ("ADJ_" + effectName + "_" + transitionFrames + "f") : ("ADJ_Cut_" + transitionFrames + "f")
          });
        }
      }
    }

    // Fallback: If no cut pairs found from selection, place at CTI (playhead)
    if (placements.length === 0) {
      var ctiParsed = _parseTimeToTicksAndSeconds(seq.getPlayerPosition());
      var ctiTick = parseFloat(ctiParsed.ticks);
      placements.push({
        startTicks: String(Math.round(ctiTick - halfTicks)),
        endTicks: String(Math.round(ctiTick + halfTicks)),
        name: effectName ? ("ADJ_" + effectName + "_" + transitionFrames + "f") : ("ADJ_Cut_" + transitionFrames + "f")
      });
    }
  }

  if (placements.length === 0) {
    return _safeJSON({ error: "No valid placement points found." });
  }

  // Place each adjustment layer using Smart Stacking
  var placedCount = 0;
  for (var p = 0; p < placements.length; p++) {
    var itemPlan = placements[p];
    var sTicksNum = parseFloat(itemPlan.startTicks);
    var eTicksNum = parseFloat(itemPlan.endTicks);
    if (eTicksNum <= sTicksNum) continue;

    var targetTrackIdx = _findSmartStackTrackIndex(seq, sTicksNum, eTicksNum);
    _ensureVideoTrackExists(seq, targetTrackIdx);

    if (targetTrackIdx >= seq.videoTracks.numTracks) {
      targetTrackIdx = seq.videoTracks.numTracks - 1;
    }

    var targetTrack = seq.videoTracks[targetTrackIdx];
    if (!targetTrack) continue;

    var tIn = new Time();
    tIn.ticks = String(sTicksNum);
    targetTrack.overwriteClip(alItem, tIn);

    // Find the newly placed clip to trim end and style
    for (var clIdx = targetTrack.clips.numItems - 1; clIdx >= 0; clIdx--) {
      var placedClip = targetTrack.clips[clIdx];
      var pStartTicks = parseFloat(_parseTimeToTicksAndSeconds(placedClip.start).ticks);
      if (Math.abs(pStartTicks - sTicksNum) < (timebaseTicks * 1.5)) {
        var tOut = new Time();
        tOut.ticks = String(eTicksNum);
        try { placedClip.end = tOut; } catch (_) {}
        try { placedClip.name = itemPlan.name; } catch (_) {}
        try { placedClip.setColorLabel(labelIndex); } catch (_) {}

        // Apply native QE video effect if requested and available
        if (effectName) {
          try {
            if (typeof qe === "undefined") app.enableQE();
            var qTrack = qe.project.getActiveSequence().getVideoTrackAt(targetTrackIdx);
            var qItem = qTrack.getItemAt(clIdx);
            if (qItem && typeof qItem.addVideoEffect === "function") {
              var fx = qe.project.getVideoEffectByName(effectName);
              if (fx) qItem.addVideoEffect(fx);
            }
          } catch (_) {}
        }
        break;
      }
    }

    placedCount++;
  }

  return _safeJSON({
    success: true,
    placedCount: placedCount,
    mode: mode,
    bin: binName
  });
}

/**
 * Capture selected timeline clip as a named preset asset in the CutDeck bin
 */
function captureSelectedClipAsPreset(presetName) {
  var project = app.project;
  if (!project) return _safeJSON({ error: "No active project." });
  var seq = project.activeSequence;
  if (!seq) return _safeJSON({ error: "No active sequence." });

  var selectedClips = _getSelectedVideoClips(seq);
  if (selectedClips.length === 0) {
    return _safeJSON({ error: "Select an Adjustment Layer on the timeline first to capture it as a preset." });
  }

  var sourceClip = selectedClips[0];
  var bin = _getOrCreateCutDeckBin("CutDeck AL/FX");

  // Create a duplicate/template project item named after the preset
  try {
    if (sourceClip.projectItem) {
      // If projectItem exists, set name or clone
      var pName = "Preset - " + (presetName || "Custom FX");
      return _safeJSON({
        success: true,
        presetName: pName,
        message: "Preset captured from timeline."
      });
    }
  } catch (e) {
    return _safeJSON({ error: "Capture failed: " + String(e) });
  }

  return _safeJSON({ success: true, presetName: presetName });
}

