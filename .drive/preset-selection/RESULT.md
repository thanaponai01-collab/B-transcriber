2026-10-14: Selected Adjustment Layer preset fix

Cause proven with the real feature/controller/selection chain against a fake Premiere host: getSelectedVideoClips excluded the only selected item because it was an Adjustment Layer. Both Transform Zoom and Invert reproduced the reported error before implementation.

Treatment: opt in to includeAdjustmentLayers only for direct selected-item preset application. Placement callers keep the default exclusion. Linked audio remains excluded; no new layer is placed.

Evidence: 36 scoped tests pass; 658 panel tests pass; Adobe API check passes for 47 panel files. RUN.json finish and status report complete. Live Premiere was not operated; reload the UXP panel and Alt-click either preset with an Adjustment Layer selected.

Verification limitation: verify-loop filtered checks pass, but strict receipt matching and challenge feature resolution did not succeed. No whole-repository strict-green claim is made. Native drive checks and the before/after regression are the completion evidence.
