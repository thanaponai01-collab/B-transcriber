"""jsx_export.py — CutPlan → ExtendScript (.jsx) that razors + ripple-deletes CUT
spans from an *already-assembled* Premiere sequence in place (IMPLEMENT_CUTDECK.md
§B.7 exception — this is the 'in-place' mode; xml_export.py remains the
'new-sequence' mode; do not merge them. See
docs/HANDOFF_CUTDECK_LIVE_SEQUENCE.md).

Frame math goes through ``transcribe.timebase`` only, same rule as xml_export.py —
no float fps or float seconds ever reaches the generated script. Frame numbers are
computed in Python via ``ms_to_frame``; the generated JSX converts a frame number to
a Premiere ``Time`` by reading the *sequence's own* ``timebase`` (ticks-per-frame) at
runtime rather than a hardcoded ticks-per-frame literal — Phase 1's acceptance note
explicitly warns against trusting an unconfirmed constant here (see
``docs/HANDOFF_CUTDECK_LIVE_SEQUENCE.md`` Phase 1).

CUT spans are processed in descending ``src_in_ms`` order (reverse chronological) so
each ripple-delete's leftward shift never invalidates a timestamp not yet visited.

The razor/ripple-delete calls use Premiere's QE (Quality Engineering) DOM — the
standard community path for this exact operation from ExtendScript, but
**unverified against a real Premiere instance**. Phase 3 (live-execution round trip,
human-verified) confirms the exact method names/signatures before this mode is
trusted on footage that matters; do not remove this caveat until that verification
has happened and is recorded in TODO_LEDGER.md.

Sync lock: Phase 0 (human-only probe, ``docs/HANDOFF_CUTDECK_LIVE_SEQUENCE.md``) has
not yet confirmed whether ripple-delete honors Premiere's sync lock automatically.
Until that finding lands, ``require_sync_lock`` defaults ``True`` and the generated
script gates every edit behind an explicit editor confirmation rather than assuming
either behavior — a false "it's fine" here risks silently desyncing a multicam
sequence, which is exactly the failure mode this handoff exists to prevent.
"""

from __future__ import annotations

from cutdeck.contracts import CUT, CutPlan
from transcribe.timebase import ms_to_frame

# Embedded in a comment ahead of each generated cut block so tests (and a human
# reading the script) can find the exact frame numbers CutDeck computed, the same
# round-trip-key discipline xml_export.py uses for its clip names.
_SPAN_MARKER = "// CUTDECK_SPAN idx={idx} in_frame={in_frame} out_frame={out_frame}"

_SYNC_LOCK_GATE = """\
    // Phase 0 (docs/HANDOFF_CUTDECK_LIVE_SEQUENCE.md) has not yet confirmed whether
    // Premiere's ripple-delete honors sync lock automatically for this project.
    // Until that probe lands, require the editor to confirm sync lock is enabled on
    // every track before any razor/ripple-delete runs — proceeding on an unconfirmed
    // assumption here risks a silently desynced multicam sequence.
    var syncLockConfirmed = confirm(
        "CutDeck: confirm sync lock is enabled on every video and audio track in " +
        "this sequence before continuing. A track without sync lock will not shift " +
        "with the others and the sequence will desync.\\n\\nProceed?"
    );
    if (!syncLockConfirmed) {
        alert("CutDeck: aborted — sync lock not confirmed.");
        return;
    }
"""

_HELPERS = """\
    function frameTicks(frameNumber) {
        // Ticks-per-frame is read from the sequence's own settings at runtime,
        // never a hardcoded literal (docs/HANDOFF_CUTDECK_LIVE_SEQUENCE.md Phase 1
        // acceptance: prefer the sequence's own ticks-per-frame over a constant).
        var t = new Time();
        t.ticks = String(frameNumber * Number(seq.timebase));
        return t;
    }

    function razorAndRipple(qeTrack, inFrame, outFrame) {
        // QE (Quality Engineering) DOM — the standard community path for razor +
        // ripple-delete from ExtendScript, but UNVERIFIED against a real Premiere
        // instance (see this module's docstring and TODO_LEDGER.md). Confirm exact
        // method names/signatures before trusting this on footage that matters.
        var inTime = frameTicks(inFrame);
        var outTime = frameTicks(outFrame);
        qeTrack.razor(inTime.ticks);
        qeTrack.razor(outTime.ticks);
        var item = qeTrack.getItemAtTime(inTime.ticks);
        if (item) { item.remove(true, true); }
    }

    function cutSpan(inFrame, outFrame) {
        // Deliberately cuts every unlocked track independently, rather than
        // cutting one track and trusting sync lock to ripple the rest: it is
        // UNVERIFIED (Phase 0, not yet run) whether a QE-level scripted
        // razor/remove call propagates across sync-locked tracks the way a
        // UI-driven ripple delete does. Cutting every track explicitly is the
        // conservative choice — it does not depend on that assumption either
        // way. If Phase 0/3 confirm QE ripples DO propagate across sync-locked
        // tracks, this loop double-cuts and must change to a single per-span
        // call; do not "fix" this without that confirmation, since guessing
        // wrong here is the exact silent-desync failure this handoff exists to
        // prevent.
        if (typeof qe === "undefined" || !qe.project) {
            app.enableQE();
        }
        var qeSeq = qe.project.getActiveSequence();
        for (var v = 0; v < seq.videoTracks.numTracks; v++) {
            var vt = seq.videoTracks[v];
            if (vt.isLocked()) { continue; }
            razorAndRipple(qeSeq.getVideoTrackAt(v), inFrame, outFrame);
        }
        for (var a = 0; a < seq.audioTracks.numTracks; a++) {
            var at = seq.audioTracks[a];
            // Skipping muted tracks is per this handoff's own spec (razor/
            // ripple-delete loop "skips locked/muted tracks"). Known tradeoff,
            // not an oversight: a muted track is NOT ripple-deleted here, so
            // unmuting it later reveals it out of sync with the rest of the
            // sequence. Revisit only if the handoff's spec changes.
            if (at.isLocked() || at.isMuted()) { continue; }
            razorAndRipple(qeSeq.getAudioTrackAt(a), inFrame, outFrame);
        }
    }
"""


def to_jsx(plan: CutPlan, *, require_sync_lock: bool = True) -> str:
    """Deterministic string generation, no side effects. Testable with no live
    Premiere instance — assert on the generated text, same discipline as
    xml_export.py's tests.

    Raises ``ValueError`` on a VFR timebase (GAP-2), same refusal xml_export.to_xml
    uses — in-place mode does not guess frame numbers on VFR sources either.
    A plan with no CUT spans is a valid, tested no-op output, not an error.
    """
    tb = plan.timebase
    if tb.is_vfr:
        raise ValueError(
            "refusing to generate in-place JSX for VFR source: no single frame grid "
            "for frame-accurate cuts (GAP-2). Conform a CFR proxy first."
        )

    cut_spans = sorted(
        (s for s in plan.spans if s.action == CUT),
        key=lambda s: s.src_in_ms,
        reverse=True,
    )

    lines: list[str] = [
        "// CutDeck in-place cut script — generated, do not hand-edit.",
        f"// job={plan.job_id} cut_spans={len(cut_spans)}",
        "(function () {",
        "    var seq = app.project.activeSequence;",
        '    if (!seq) { alert("CutDeck: no active sequence."); return; }',
    ]
    if require_sync_lock:
        lines.append(_SYNC_LOCK_GATE)
    lines.append(_HELPERS)

    if not cut_spans:
        lines.append("    // no CUT spans in this plan — nothing to do.")
        lines.append("})();")
        return "\n".join(lines) + "\n"

    for s in cut_spans:
        in_frame = ms_to_frame(s.src_in_ms, tb)
        out_frame = ms_to_frame(s.src_out_ms, tb)
        lines.append(
            "    " + _SPAN_MARKER.format(idx=s.idx, in_frame=in_frame, out_frame=out_frame)
        )
        lines.append(f"    cutSpan({in_frame}, {out_frame});")

    lines.append("})();")
    return "\n".join(lines) + "\n"
