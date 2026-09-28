"""cutdeck/live_check.py: each missing piece of the live stack is named, in order, and stops there."""
import pytest

from cutdeck import live_check
from cutdeck.driver_commands import COMMANDS


class _FakeBackend:
    status = {"connected": True, "commands": list(COMMANDS)}
    status_error = None
    sequence_error = None
    selected = 0

    def __init__(self, port=None):
        pass

    async def premiere_status(self):
        if self.status_error:
            raise self.status_error
        return self.status

    async def premiere(self, command, args=None):
        if command == "read_sequence":
            if self.sequence_error:
                raise self.sequence_error
            return {"name": "Seq", "video_track_count": 2, "audio_track_count": 3}
        assert command == "inspect_selection"
        # like the real panel: with no selection it still lists every video clip
        return {"has_selection": self.selected > 0, "selected_count": self.selected or 4, "items": []}


@pytest.fixture
def stack(monkeypatch):
    class B(_FakeBackend):
        pass
    monkeypatch.setattr(live_check, "Backend", B)
    monkeypatch.setattr(live_check, "premiere_running", lambda: True)
    return B


def names(steps):
    return [(s.name.split(" ")[0], s.ok) for s in steps]


def test_everything_up_passes_every_step_and_reports_the_selection(stack):
    steps, selection = live_check.check()
    assert all(s.ok for s in steps) and len(steps) == 6
    assert selection["has_selection"] is False
    assert "nothing selected" in steps[-1].detail


def test_premiere_not_running_stops_at_the_first_step(stack, monkeypatch):
    monkeypatch.setattr(live_check, "premiere_running", lambda: False)
    steps, selection = live_check.check()
    assert [s.ok for s in steps] == [False] and selection is None
    assert "start Premiere" in steps[0].detail


def test_helper_down_stops_after_premiere_and_says_how_to_start_it(stack):
    stack.status_error = ValueError("CutDeck helper is not running on 127.0.0.1:7891")
    steps, selection = live_check.check()
    assert [s.ok for s in steps] == [True, False] and selection is None
    assert "not running" in steps[1].detail


def test_panel_not_connected_stops_there(stack):
    stack.status = {"connected": False, "commands": []}
    steps, _ = live_check.check()
    assert [s.ok for s in steps] == [True, True, False]
    assert "open the CutDeck panel" in steps[2].detail


def test_an_older_panel_missing_a_command_is_named(stack):
    stack.status = {"connected": True, "commands": [c for c in COMMANDS if c != "align_clips"]}
    steps, _ = live_check.check()
    assert [s.ok for s in steps] == [True, True, True, False]
    assert "align_clips" in steps[3].detail


def test_unreadable_sequence_carries_the_panels_reason(stack):
    stack.sequence_error = ValueError("Set In and Out marks first")
    steps, _ = live_check.check()
    assert steps[-1].ok is False and "Set In and Out marks first" in steps[-1].detail


def test_a_selection_is_flagged_as_editable(stack):
    stack.selected = 2
    steps, selection = live_check.check()
    assert selection["selected_count"] == 2
    assert "WILL edit" in steps[-1].detail


def test_main_exit_code_follows_the_steps(stack, monkeypatch, capsys):
    assert live_check.main() == 0
    monkeypatch.setattr(live_check, "premiere_running", lambda: False)
    assert live_check.main() == 1
    assert "FAIL" in capsys.readouterr().out
