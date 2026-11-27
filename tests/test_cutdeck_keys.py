"""Keyboard route (cutdeck/keys.py): .kys parsing, which binding is pressed, and the focus guard."""
import asyncio

import pytest

from cutdeck import keys, menu

KYS = """<?xml version="1.0" encoding="UTF-8"?>
<PremiereData Version="3"><shortcuts Version="6"><platform>windows</platform>
<mode.Edit Version="1">
 <context.global Version="1"><itemcount>6</itemcount>
  <item.0 Version="1"><commandname>cmd.sequence.razorateditline.all</commandname>
   <modifier.shift>false</modifier.shift><modifier.alt>true</modifier.alt><modifier.ctrl>true</modifier.ctrl>
   <virtualkey>2147483738</virtualkey></item.0>
  <item.1 Version="1"><commandname>cmd.sequence.razorateditline.all</commandname>
   <modifier.shift>true</modifier.shift><modifier.alt>false</modifier.alt><modifier.ctrl>true</modifier.ctrl>
   <virtualkey>2147483723</virtualkey></item.1>
  <item.2 Version="1"><commandname>cmd.edit.rippledelete</commandname>
   <modifier.shift>true</modifier.shift><modifier.alt>false</modifier.alt><modifier.ctrl>false</modifier.ctrl>
   <virtualkey>35</virtualkey></item.2>
  <item.3 Version="1"><commandname>cmd.file.exit</commandname>
   <modifier.shift>false</modifier.shift><modifier.alt>false</modifier.alt><modifier.ctrl>true</modifier.ctrl>
   <virtualkey>2147483729</virtualkey></item.3>
  <item.4 Version="1"><commandname>cmd.odd.key</commandname>
   <modifier.shift>false</modifier.shift><modifier.alt>false</modifier.alt><modifier.ctrl>false</modifier.ctrl>
   <virtualkey>3221225522</virtualkey></item.4>
  <item.5 Version="1"><commandname>cmd.unbound</commandname></item.5>
 </context.global>
</mode.Edit>
<mode.Color Version="1"><context.global Version="1"><itemcount>0</itemcount></context.global></mode.Color>
</shortcuts></PremiereData>"""


@pytest.fixture()
def table(tmp_path, monkeypatch):
    path = tmp_path / "user.kys"
    path.write_text(KYS, encoding="utf-8")
    monkeypatch.setattr(keys, "active_kys", lambda: path)
    return keys.load(path)


def test_parses_bindings_and_key_names(table):
    assert [s.keys() for s in table["cmd.sequence.razorateditline.all"]] == ["Ctrl+Alt+Z", "Ctrl+Shift+K"]
    assert table["cmd.edit.rippledelete"][0].keys() == "Shift+Delete"
    assert "cmd.unbound" not in table


def test_a_ctrl_alt_binding_is_picked_last(table):
    # Live 2026-11-21: the user's Ctrl+Alt+Z did nothing, Ctrl+Shift+K cut.
    assert keys.pick(table, "cmd.sequence.razorateditline.all").keys() == "Ctrl+Shift+K"


def test_blocked_unbound_and_unknown_keys_are_refused(table):
    for command, why in (("cmd.file.exit", "never pressed"), ("cmd.nothing", "no shortcut"), ("cmd.odd.key", "cannot press")):
        with pytest.raises(ValueError, match=why):
            keys.pick(table, command)
    listed = {c["command"]: c["pressable"] for c in keys.list_commands()}
    assert listed["cmd.file.exit"] is False and listed["cmd.odd.key"] is False and listed["cmd.edit.rippledelete"] is True


class FakeBackend:
    def __init__(self, actives):
        self.actives, self.calls = list(actives), []

    async def premiere(self, command, args=None):
        self.calls.append((command, args))
        if command == "read_sequence":
            return {"name": self.actives.pop(0)}
        return {}


def test_presses_only_when_the_timeline_kept_the_sequence(table, monkeypatch):
    pressed, posted = [], []
    monkeypatch.setattr(keys, "focus_panel", lambda panel: pytest.fail("timeline focus goes through the menu"))
    monkeypatch.setattr(menu, "invoke", lambda path, front=False: posted.append(path) or {})
    monkeypatch.setattr(keys, "press_command", lambda command: pressed.append(command) or {"command": command})
    ok = FakeBackend(["Edit", "Edit"])
    out = asyncio.run(keys.run_command(ok.premiere, "cmd.edit.rippledelete", "timeline", "Edit"))
    assert pressed == ["cmd.edit.rippledelete"] and out["sequence"] == "Edit"
    assert ok.calls[0] == ("open_sequence", {"sequence": "Edit"})
    assert posted == ["Window > Timelines > Edit"]  # the named timeline, never a cycling key

    moved = FakeBackend(["Edit", "ALL"])
    with pytest.raises(RuntimeError, match="switched to 'ALL'"):
        asyncio.run(keys.run_command(moved.premiere, "cmd.edit.rippledelete", "timeline"))
    assert pressed == ["cmd.edit.rippledelete"]  # nothing more pressed
    assert moved.calls[-1] == ("open_sequence", {"sequence": "Edit"})  # the right sequence is reopened


def test_a_blocked_command_touches_nothing(table, monkeypatch):
    monkeypatch.setattr(keys, "focus_panel", lambda panel: pytest.fail("focused"))
    backend = FakeBackend([])
    with pytest.raises(ValueError):
        asyncio.run(keys.run_command(backend.premiere, "cmd.file.exit"))
    assert backend.calls == []


def test_menu_labels_and_what_is_never_run():
    assert menu._clean("&Add Edit to All Tracks	Ctrl+Alt+Z") == ("Add Edit to All Tracks", "Ctrl+Alt+Z")
    assert menu._clean("Save && Close") == ("Save & Close", "")
    item = lambda path: {"path": path}
    assert menu.runnable(item("Edit > Undo")) and menu.runnable(item("Sequence > Add Edit to All Tracks"))
    for path in ("File > Exit", "File > Close Project", "File > Export > Media...", "File > Save As...",
                 "Clip > Speed/Duration...", "Help > Premiere Pro Help..."):
        assert not menu.runnable(item(path)), path


def test_menu_find_refuses_blocked_dialog_and_unknown(monkeypatch):
    fake = [{"path": "Edit > Undo", "keys": "Ctrl+Z", "id": 57643, "enabled_hint": True},
            {"path": "File > Exit", "keys": None, "id": 1, "enabled_hint": True},
            {"path": "Clip > Nest...", "keys": None, "id": 2, "enabled_hint": True}]
    monkeypatch.setattr(menu, "items", lambda window=None: fake)
    assert menu.find("edit >undo")["id"] == 57643
    for path, why in (("File > Exit", "never run"), ("Clip > Nest...", "dialog"), ("Edit > Nope", "No menu item")):
        with pytest.raises(ValueError, match=why):
            menu.find(path)


def test_a_bare_letter_is_sent_without_shift(monkeypatch):
    # The .kys stores letters uppercase (W = 0x80000057); typing 'W' needs Shift, so W went out as
    # Shift+W (Extend Next Edit) and rolled the edit (PREMIERE_FACTS "Keys sent letters with Shift").
    sent = []
    monkeypatch.setattr(keys, "_send", sent.append)
    keys.press(keys.Shortcut("cmd.sequence.rippletrimnextedittoplayhead", "global", False, False, False, 0x80000057))
    keys.press(keys.Shortcut("cmd.sequence.extendnextedittoplayhead", "global", False, True, False, 0x80000057))
    keys.press(keys.Shortcut("cmd.sequence.razorateditline", "global", True, False, False, 0x8000004B))
    assert sent == [[0x57], [0x10, 0x57], [0x11, 0x4B]]
