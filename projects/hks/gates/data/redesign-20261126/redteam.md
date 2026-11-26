# Red-team: ways around the helper's gate status

Each bypass is tried offline against hks_gate_store / hks_enforce, with a test named in the table. "Live" means it still needs the verify-cutdeck run.

| Bypass | Route | Result | Proof |
|---|---|---|---|
| Rename a failed draft to look like a final ("1 YOUTUBE D1") | F2 or Project panel (helper never sees it), `edit_clips` renames clips only | Still **fail**: keyed by GUID, not name | test_status_follows_the_saved_cut_not_the_name; live: UXP guid == prproj ObjectUID still to prove |
| Label clips through the menu (Edit > Label > *) after passing | `menu_command`, or by hand | **Ungated** "changed after its last gate run": the label is in the cut hash | test_a_label_change_is_an_edit |
| Label the sequence's project item | Project panel, by hand | No effect: identity is the GUID. A label marks nothing | offline scan: 0 of 85 sequences on 1123–1125 carry an item label |
| Edit after passing, then save | any route | **Ungated** until hks_handover runs again | test_status_follows_the_saved_cut_not_the_name |
| Edit after passing, no save | any route | Panel shows the last save's status; hks_handover always saves first | by design; status says "checked <time>" |
| Duplicate a failed draft and hand over the copy | live through `duplicate_sequence` (UXP clone); menu Sequence > Duplicate and right-click not run | New GUID: **ungated**, and `new` after a day baseline, whatever its name | test_a_sequence_made_after_the_baseline_is_new_whatever_its_name |
| Override with no reason | `premiere_hks_handover overrides={gate: ""}` | **Refused** before anything runs (argument check and handover) | test_an_override_with_no_reason_is_refused_before_anything_runs |
| Override with a reason | same | Passes the control. The panel row lists "N overridden" | by design; who may override is your decision |
| Narrow the body (`body_from` late, or `show_end` early) | the two numbers the agent gives | **Fail** `body_range` when the body starts after 45 s or runs under 900 s; the row shows both | test_a_body_start_past_the_hook_and_sting_fails, test_a_show_end_that_leaves_a_short_body_fails |
| Write a passing record into records.jsonl by hand | file system | Ignored: a signed fail stays **fail**; with no signed record the draft is **ungated** "record not signed by the helper" | test_a_forged_pass_after_a_signed_fail_leaves_the_fail, test_a_record_written_by_hand_is_not_trusted. Measured before the fix: the forged line turned 1125 v1 from fail to pass |
| Same, after reading the key in %LOCALAPPDATA%\CutDeck\hks_gate.key | file system | **Not blocked.** Same Windows user, so no file the helper can read is out of the agent's reach | residual; would need a separate OS account or a service |
| Lower a line or retire a gate in projects/hks/gates/registry.json | git | Not blocked. Visible in the diff, and the record stores the line it used | residual |
| Answer every do–confirm item with "done" | `answers` | **Passes** (presence check) | do_confirm experiment: stronger checks don't catch K22 either |
| Hand over without calling hks_handover | any | **Ungated** in the panel; no record exists | by design |
