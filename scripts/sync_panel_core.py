"""Mirror panel/core/*.js and *.css into the UXP panel's own folder.

UXP loads or zips uxp/cutdeck, so it can't reach a sibling folder at runtime.
panel/core is the one place to edit; the mirror is generated.
tests/panel_core_sync.test.cjs fails when the mirror drifts.
"""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "panel" / "core"
MIRRORS = [ROOT / "uxp" / "cutdeck" / "core"]


def main():
    for mirror in MIRRORS:
        mirror.mkdir(parents=True, exist_ok=True)
        for source in sorted(SOURCE.glob("*.js")) + sorted(SOURCE.glob("*.css")):
            shutil.copyfile(source, mirror / source.name)
            print(f"{source.relative_to(ROOT)} -> {(mirror / source.name).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
