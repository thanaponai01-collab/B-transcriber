"""Which raw source reaches each Premiere timeline verb: the source half of the verb coverage matrix
(docs/research/timeline-verb-matrix-2026-11-27.md).

Sources, each read raw:
  uxp    reference/adobe/api/premierepro.txt (27.0.0 typings, one line per member)
  allow  the third-party allow-list JSON embedded in Adobe Premiere Pro.exe (backend class names)
  cs     the Control Surface command catalog (native plugin listing, 26.5.2; not re-run on 27.0)
  kys    the user's newest .kys and Premiere's Defaults.kys (bindings that differ are flagged)
  menu   the live Win32 menu bar (cutdeck.menu.list_items, read-only)

    python tools/adobe/timeline_verbs.py [--catalog PATH] [--kys PATH] [--exe PATH] > out.md
"""
from __future__ import annotations

import argparse
import json
import mmap
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXE = Path(r"C:\Program Files\Adobe\Adobe Premiere Pro 2027\Adobe Premiere Pro.exe")
CATALOG = ROOT / "output/native-cutter-spike/live/commands-35300-29954531-1.json"
USER_KYS = max((p for root in (Path.home() / "OneDrive/Documents", Path.home() / "Documents")
                for p in (root / "Adobe/Premiere Pro").glob("*/Profile-*/Win/*.kys")),
               key=lambda p: (p.parts[-4], p.stat().st_mtime), default=None)

# verb: (premierepro.txt member regex, allow-list "Class.member" regex, command-id regex, menu path regex)
VERBS: dict[str, tuple[str, str, str, str]] = {
    "place": (r"SequenceEditor\.(createOverwriteItemAction|createInsertProjectItemAction|insertMogrt)",
              r"SequenceEditor\.createAddItems?Action", r"^cmd\.clip\.(overlay|insert)$", r"^Clip > (Insert|Overwrite)$"),
    "move": (r"TrackItem\.createMoveAction", r"TrackItem\.createMoveAction",
             r"^cmd\.timeline\.nudge\.", r"^$"),
    "ripple": (r"createRemoveItemsAction", r"SequenceEditor\.createRemoveItemsAction",
               r"ripple|rippletrim|toggletrimtype|tools\.03ripple", r"Ripple Delete"),
    "roll": (r"^$", r"^$", r"rolledit|select\.nearest\.edit\.as\.roll|trimforward|trimbackward|tools\.04roll|extend(next|previous)edit", r"Trim Edit"),
    "slip": (r"^$", r"^$", r"slip", r"^$"),
    "slide": (r"^$", r"^$", r"slide", r"^$"),
    "razor": (r"[Rr]azor|SequenceUtils\.(performSceneEdit|SEQUENCE_OPERATION_APPLYCUT)",
              r"[Rr]azor|SequenceUtils\.(performSceneEdit|SEQUENCE_OPERATION_APPLYCUT)",
              r"razor|splitclip", r"Add Edit|Scene Edit Detection"),
    "lift": (r"createLift", r"createLift", r"^cmd\.sequence\.lift$|^cmd\.edit\.clear$", r"^Sequence > Lift$|^Edit > Clear$"),
    "extract": (r"createExtract", r"createExtract", r"^cmd\.sequence\.extract$", r"^Sequence > Extract$"),
    "link/unlink": (r"[Ll]ink(?!ed)|getLinked", r"\.[a-z]*[Ll]ink(?!ed)", r"linkaudioandvideo|linkedselection|trackitem\.(un)?linkmedia", r"Clip > (Un)?[Ll]ink|Linked Selection"),
    "group": (r"[Gg]roup(?!Index)", r"TrackItem\..*[Gg]roup", r"^cmd\.(clip\.(un)?group|edit\.creategroup)$", r"Clip > (Un)?[Gg]roup"),
    "targeting": (r"[Tt]arget", r"[Tt]arget", r"tlnav\..*target|tlnav\.move\.all\.(source|target)", r"^$"),
    "3-point overwrite/insert": (r"SourceMonitor\.|createSetInOutPointsAction|createOverwriteItemAction|createInsertProjectItemAction",
                                 r"SourceMonitorAPI\.|MasterClip\.createSetInOutPointsAction",
                                 r"^cmd\.clip\.(overlay|insert)$|^cmd\.(clear|common)\.(in|out|setin|setout)", r"^Clip > (Insert|Overwrite)$|Match Frame"),
    "speed": (r"[Ss]peed|TimeRemap", r"[Ss]peed", r"^cmd\.clip\.speed$|timeremap|reverse", r"Speed/Duration"),
    "nest": (r"createSubsequence|[Nn]est", r"createSubsequence|[Nn]est", r"nestify|nestsourcesequence|reveal\.nested", r"Nest|Make Subsequence"),
    "frame hold": (r"[Ff]rameHold|[Hh]old", r"[Ff]rameHold", r"framehold", r"Frame Hold"),
    "effects": (r"ComponentChain\.create(Append|Insert|Remove)ComponentAction|FilterFactory\.|createAddVideoTransitionAction",
                r"ComponentChain\.create|FilterFactory\.|createAddVideoTransitionAction",
                r"pasteattributes|deleteeffects|delete\.all\.effects|effects\.enabled", r"Paste Attributes|Remove Attributes|Apply (Video|Audio) Transition"),
    "keyframes": (r"ComponentParam\.(createAddKeyframeAction|createKeyframe|createRemoveKeyframe|createSetTimeVarying|createSetInterpolation)|Keyframe\.setTemporal",
                  r"ComponentParam\.create|Keyframe\.setTemporal", r"keyframe|interpolation", r"^$"),
    "text": (r"MogrtText|insertMogrt|TextSegments", r"MogrtText|MogrtImport|SequenceEditor\.insertMogrt",
             r"graphics\.(add\.text|enter\.text\.edit|upgrade)|tools\.12text|file\.new\.textstyle", r"New Layer > (Vertical )?Text|Upgrade Caption"),
}


def uxp_members() -> list[str]:
    lines = (ROOT / "reference/adobe/api/premierepro.txt").read_text(encoding="utf-8").splitlines()
    return [l.split("(")[0].split(":")[0].strip() for l in lines if l and not l.startswith("#")]


def allow_list(exe: Path) -> list[str]:
    """Class.member for every entry of the {"<Class>": [members], "hash": ...} blocks in the exe."""
    with exe.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
        at = m.find(b'"SequenceEditor": [')
        if at < 0:
            raise SystemExit(f"no allow-list in {exe}")
        start = m.rfind(b'"apis"', 0, at)
        end = m.find(b"}\x00", at)  # the JSON ends `"version": "...", }` then a NUL (27.0.0)
        if start < 0 or end < 0:
            raise SystemExit(f'the allow-list in {exe} has no "apis" start or no end')
        blob = m[max(start - 64, 0):end + 64].decode("utf-8", "replace")
    found = re.findall(r'\{\s*"(\w+)":\s*\[(.*?)\],\s*"hash"', blob, re.S)
    return [f"{cls}.{name}" for cls, body in found for name in re.findall(r'"(\w+)"', body)]


def catalog(path: Path) -> list[str]:
    return sorted({c["commandID"] for c in json.loads(path.read_text(encoding="utf-8"))["commands"]})


def main() -> None:
    from cutdeck import keys, menu

    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", type=Path, default=EXE)
    ap.add_argument("--catalog", type=Path, default=CATALOG)
    ap.add_argument("--kys", type=Path, default=USER_KYS)
    a = ap.parse_args()
    if a.kys is None:
        raise SystemExit(r"no .kys found under Documents or OneDrive\Documents; pass --kys")
    uxp, allow, cs = uxp_members(), allow_list(a.exe), catalog(a.catalog)
    user, dflt = keys.load(a.kys), keys.load(keys.DEFAULTS)
    menu_items = menu.list_items()
    bind = lambda t, c: "/".join(s.keys() for s in t.get(c, [])) or "-"

    print(f"Sources: {len(uxp)} typed members; {len(allow)} allow-list entries; {len(cs)} catalog ids (26.5.2); "
          f"{a.kys.name} {len(user)} + Defaults {len(dflt)} bound commands; {len(menu_items)} menu items.\n")
    for verb, (u_re, a_re, c_re, m_re) in VERBS.items():
        pick = lambda rx, xs: [x for x in xs if rx != "^$" and re.search(rx, x)]
        cmds = sorted(set(pick(c_re, cs)) | set(pick(c_re, list(user) + list(dflt))))
        print(f"### {verb}\n")
        print(f"- uxp (typings): {', '.join(pick(u_re, uxp)) or 'none'}")
        print(f"- allow-list: {', '.join(pick(a_re, allow)) or 'none'}")
        print(f"- menu: {', '.join(m['path'] + ('' if m['runnable'] else ' [not run]') for m in menu_items if m_re != '^$' and re.search(m_re, m['path'])) or 'none'}")
        print("- commands (cs = in the catalog; user / default binding; ! = they differ):")
        for c in cmds:
            u, d = bind(user, c), bind(dflt, c)
            print(f"  - `{c}` {'cs' if c in cs else 'not-cs'}; {u} / {d}{' !' if u != d else ''}")
        print()


if __name__ == "__main__":
    main()
