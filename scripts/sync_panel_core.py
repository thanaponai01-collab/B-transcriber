"""Mirror panel/core/*.js and *.css into each Premiere panel's own folder.

CEP loads cep/cutdeck through a directory junction and UXP loads or zips uxp/cutdeck, so
neither panel can reach a sibling folder at runtime. panel/core is the one place to edit;
the mirrors are generated. tests/panel_core_sync.test.cjs fails when a mirror drifts.
"""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "panel" / "core"
MIRRORS = [ROOT / "cep" / "cutdeck" / "client" / "core", ROOT / "uxp" / "cutdeck" / "core"]


def main():
    for mirror in MIRRORS:
        mirror.mkdir(parents=True, exist_ok=True)
        for source in sorted(SOURCE.glob("*.js")) + sorted(SOURCE.glob("*.css")):
            shutil.copyfile(source, mirror / source.name)
            print(f"{source.relative_to(ROOT)} -> {(mirror / source.name).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
