# CutDeck CEP Extension for Adobe Premiere Pro

Permanent Premiere Pro extension (`Window > Extensions > CutDeck`) using Adobe's Common Extensibility Platform (CEP).

**Role: the production panel** — the one to use day to day. Its sibling `uxp/cutdeck` is experimental (see its README). Both talk to the same helper on `ws://127.0.0.1:7891` (`Start CutDeck.cmd`); there is no other CutDeck server.

## Features
- **No UXP Developer Tool required**: Runs automatically whenever Premiere Pro opens.
- **Direct WebSocket connectivity**: Connects to the local Python helper (`ws://127.0.0.1:7891`) with zero cold-start permission prompt bugs.
- **Clean XML rough-cut workflow**: Captures timeline In/Out points, exports sequence XML, recuts via the Python helper, and opens the new rough cut.

## Installation
Run the installer script:
```powershell
python scripts/install_cutdeck_cep.py
```
This enables `PlayerDebugMode` in the Windows Registry and creates a directory link in `%APPDATA%\Adobe\CEP\extensions\CutDeck`.

## Usage
1. Start the CutDeck helper: double-click **`Start CutDeck.cmd`** in the project folder.
2. In Premiere Pro, mark timeline **In (`I`)** and **Out (`O`)** on your sequence.
3. Open **`Window > Extensions > CutDeck`**.
4. Click **Read timeline range**.
5. Click **Rough Cut In–Out**.
6. CutDeck exports the sequence, removes silence and speech fillers according to your preset, and opens the resulting sequence automatically.
