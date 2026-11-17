"""premiere_assistant_ask: reading a reply out of Premiere's AI Assistant panel.

The element lists are the panel's tree as read live on 2026-11-17 (Premiere 27.0.0.88) after
asking NAME and then TRACKS; the UI Automation itself needs a running Premiere and is not
exercised here.
"""
import asyncio

import pytest

from cutdeck import assistant
from cutdeck.ai_backend import Backend
from cutdeck.mcp_server import create_server

NAME = "What is the name of the active sequence?"
TRACKS = "How many video tracks and how many audio tracks does the active sequence have?"


def _tree(*rows):
    return [{"type": kind, "name": name, "depth": depth, "leaf": leaf} for kind, name, depth, leaf in rows]


def _asked(prompt, time):
    return _tree(("Group", "", 7, False), ("Text", prompt, 8, True),
                 ("Group", "", 7, False), ("Text", time, 8, True),
                 ("Group", "", 7, False), ("Text", "Reasoning", 8, True))


def _finished(credits):
    return _tree(("Button", "Like", 7, True), ("Button", "Dislike", 7, True),
                 ("Button", "Report content", 7, True), ("Button", f"Used {credits} credits", 7, True),
                 ("Button", "Copy", 7, True))


NAME_REPLY = _tree(("Group", "", 7, False), ("Group", "", 8, False),
                   ("Text", "The active sequence is ", 9, True), ("Text", "", 9, False),
                   ("Text", "2026-11-17 09-30-15", 10, True), ("Text", ". It runs about 4:31.", 9, True))
TRACKS_REPLY = _tree(
    ("Group", "", 7, False), ("List", "", 8, False),
    ("ListItem", "Video tracks: 3 (V1 to V3), all empty", 9, False), ("Text", "• ", 10, True),
    ("Text", "", 10, False), ("Text", "Video tracks:", 11, True), ("Text", " 3 (V1 to V3), all empty", 10, True),
    ("ListItem", "Audio tracks: 4 (A1 to A4).", 9, False), ("Text", "• ", 10, True),
    ("Text", "", 10, False), ("Text", "Audio tracks:", 11, True), ("Text", " 4 (A1 to A4).", 10, True),
    ("Group", "", 8, False), ("Text", "I didn't change anything.", 9, True))
COMPOSER = _tree(("Group", "", 4, False), ("Group", "", 5, False),
                 ("Edit", "Describe what you want to do", 6, True), ("Button", "Permission mode", 5, True),
                 ("Button", "Send", 5, True), ("Group", "", 5, False),
                 ("Text", "Responses are generated using AI, and may be inaccurate.", 6, True))
FIRST = _asked(NAME, "November 17, 2026 at 9:44:44 AM") + NAME_REPLY + _finished("3.32")
SECOND = _asked(TRACKS, "November 17, 2026 at 9:48:28 AM") + TRACKS_REPLY + _finished("3.99")
PANEL = FIRST + SECOND + COMPOSER


def test_inline_pieces_of_a_paragraph_join_into_one_line():
    assert assistant.parse_reply(FIRST + COMPOSER, NAME) == {
        "done": True, "text": "The active sequence is 2026-11-17 09-30-15. It runs about 4:31.",
        "credits": 3.32, "buttons": []}


def test_list_items_and_paragraphs_each_get_a_line():
    assert assistant.parse_reply(PANEL, TRACKS) == {
        "done": True, "credits": 3.99, "buttons": [],
        "text": ("• Video tracks: 3 (V1 to V3), all empty\n• Audio tracks: 4 (A1 to A4).\n"
                 "I didn't change anything.")}


def test_an_earlier_message_stops_at_its_own_buttons():
    reply = assistant.parse_reply(PANEL, NAME)
    assert reply["text"].endswith("It runs about 4:31.") and reply["credits"] == 3.32


def test_only_the_last_asking_of_a_repeated_prompt_counts():
    again = FIRST + _asked(NAME, "later") + TRACKS_REPLY[:1] + TRACKS_REPLY[-2:] + _finished("1.5") + COMPOSER
    assert assistant.parse_reply(again, NAME)["text"] == "I didn't change anything."


def test_reply_without_a_like_button_is_not_done_and_lists_its_buttons():
    waiting = (_asked(NAME, "now") + NAME_REPLY[:3] + _tree(("Button", "Allow", 8, True)) + COMPOSER)
    assert assistant.parse_reply(waiting, NAME) == {
        "done": False, "text": "The active sequence is", "credits": None, "buttons": ["Allow"]}


def test_prompt_not_on_screen_yet_is_not_done():
    assert assistant.parse_reply(COMPOSER, NAME)["done"] is False


def test_same_prompt_again_waits_for_the_new_message(monkeypatch):
    """The old identical message is finished and on screen; it must not be returned."""
    newer = _asked(NAME, "later") + TRACKS_REPLY[:1] + TRACKS_REPLY[-2:] + _finished("1.5")
    panels = iter([FIRST + COMPOSER, FIRST + COMPOSER, FIRST + newer + COMPOSER])
    monkeypatch.setattr(assistant, "_panel", lambda prompt=None: next(panels))
    monkeypatch.setattr(assistant.time, "sleep", lambda _: None)
    assert assistant.ask(NAME)["text"] == "I didn't change anything."


def test_ask_polls_until_the_reply_is_done(monkeypatch):
    asked = _asked(NAME, "now")
    panels = iter([COMPOSER, asked + COMPOSER, asked + NAME_REPLY[:3] + COMPOSER, FIRST + COMPOSER])
    sent = []

    def panel(prompt=None):
        sent.append(prompt)
        return next(panels)

    monkeypatch.setattr(assistant, "_panel", panel)
    monkeypatch.setattr(assistant.time, "sleep", lambda _: None)
    assert assistant.ask("What is the name\nof the  active sequence?")["credits"] == 3.32
    assert sent == [None, NAME, None, None]  # counted, typed once as one line, then only read


def test_ask_gives_up_at_the_timeout_with_what_is_on_screen(monkeypatch):
    panels = iter([COMPOSER, _asked(NAME, "now") + NAME_REPLY[:3] + COMPOSER])
    monkeypatch.setattr(assistant, "_panel", lambda prompt=None: next(panels))
    assert assistant.ask(NAME, timeout_s=0) == {
        "done": False, "text": "The active sequence is", "credits": None, "buttons": []}


def test_empty_prompt_is_refused_before_touching_premiere(monkeypatch):
    monkeypatch.setattr(assistant, "_panel", lambda prompt=None: pytest.fail("typed into Premiere"))
    with pytest.raises(ValueError):
        assistant.ask("  ")


def test_tool_is_published():
    assert "premiere_assistant_ask" in Backend().capabilities()["tools"]
    tools = asyncio.run(create_server(Backend()).list_tools())
    assert "premiere_assistant_ask" in {tool.name for tool in tools}
