"""Build a local CCX (ZIP) package when UXP Developer Tool isn't installed."""
from pathlib import Path
import json
import zipfile


def main():
    root = Path(__file__).resolve().parent.parent
    source = root / "uxp/cutdeck"
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    out = root / "output" / f"CutDeck-{manifest['version']}.ccx"
    out.parent.mkdir(parents=True, exist_ok=True)
    files = ["manifest.json", "index.html", "main.js", "workflow.js", "rpc.js", "icons/icon.svg"]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            archive.write(source / name, name)
    with zipfile.ZipFile(out) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == set(files)
    print(out)


if __name__ == "__main__":
    main()
