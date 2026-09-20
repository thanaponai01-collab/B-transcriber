"""Install CutDeck CEP extension for Adobe Premiere Pro.

1. Enables Adobe PlayerDebugMode in Windows Registry for CSXS 9 - 16.
2. Creates a directory junction in %APPDATA%/Adobe/CEP/extensions/CutDeck
   pointing to the local cep/cutdeck source directory.
"""
import os
from pathlib import Path
import subprocess
import sys


def enable_player_debug_mode():
    if sys.platform != "win32":
        print("Note: PlayerDebugMode registry setup is only required on Windows.")
        return

    import winreg

    versions = [9, 10, 11, 12, 13, 14, 15, 16]
    for v in versions:
        key_path = f"Software\\Adobe\\CSXS.{v}"
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValueEx(key, "PlayerDebugMode", 0, winreg.REG_SZ, "1")
        except OSError as e:
            print(f"Warning: Could not set PlayerDebugMode for CSXS.{v}: {e}")
    print("[OK] Enabled Adobe PlayerDebugMode in Windows Registry.")


def install_extension():
    root = Path(__file__).resolve().parent.parent
    source = (root / "cep" / "cutdeck").resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source directory not found: {source}")

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise EnvironmentError("APPDATA environment variable not found.")
        cep_dir = Path(appdata) / "Adobe" / "CEP" / "extensions"
    else:
        cep_dir = Path.home() / "Library" / "Application Support" / "Adobe" / "CEP" / "extensions"

    cep_dir.mkdir(parents=True, exist_ok=True)
    target = cep_dir / "CutDeck"

    if target.exists() or target.is_symlink():
        print(f"Target already exists: {target}")
        if target.is_symlink() or target.is_dir():
            if sys.platform == "win32":
                subprocess.run(["cmd", "/c", "rmdir", str(target)], check=True)
            else:
                target.unlink()
            print("  Removed existing junction/symlink.")

    if sys.platform == "win32":
        cmd = ["cmd", "/c", "mklink", "/J", str(target), str(source)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create junction: {result.stderr.strip() or result.stdout.strip()}")
    else:
        target.symlink_to(source)

    print(f"[OK] Installed CutDeck extension to {target}")
    print(f"  Linked to source: {source}")
    print("\nNext steps:")
    print("1. Start the CutDeck helper: double-click 'Start CutDeck.cmd'")
    print("2. Open Premiere Pro")
    print("3. Go to Window > Extensions > CutDeck")


if __name__ == "__main__":
    print("--- CutDeck CEP Extension Installer ---")
    enable_player_debug_mode()
    install_extension()
    print("---------------------------------------")
