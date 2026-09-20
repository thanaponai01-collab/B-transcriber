"""Learn display preferences and wrap cues without changing speech or timing."""
from __future__ import annotations

from dataclasses import dataclass
import statistics

from transcribe.subtitles import read_subtitles


@dataclass(frozen=True)
class LayoutProfile:
    target_line_chars: int = 24
    wrap_threshold_chars: int = 32
    training_cues: int = 0
    multiline_cues: int = 0
    median_cue_ms: float = 0

    def __post_init__(self):
        if self.target_line_chars < 1 or self.wrap_threshold_chars < 1:
            raise ValueError('Line sizes must be positive')


def fit_profile(corrected_srts: list[str]) -> LayoutProfile:
    """Fit display length statistics only; never learn word replacements.

    Multi-line prevalence is learned as a threshold classifier. This cannot
    learn speaker identity or semantic phrase boundaries from unlabelled SRTs.
    """
    cues = [c for srt in corrected_srts for c in read_subtitles(srt, preserve_line_breaks=True)]
    if not cues:
        raise ValueError('No corrected captions to learn from')
    multiline = [c for c in cues if '\n' in c['text']]
    lines = [len(line.strip()) for c in (multiline or cues) for line in c['text'].splitlines() if line.strip()]
    lengths = [(len(c['text'].replace('\n', '')), '\n' in c['text']) for c in cues]
    # Misclassification cost treats missed and unnecessary wraps equally.
    # Prefer the larger threshold on ties to avoid unnecessary two-line cues.
    candidates = range(1, max(n for n, _ in lengths) + 2)
    threshold = min(candidates, key=lambda t: (sum((n >= t) != wrapped for n, wrapped in lengths), -t))
    return LayoutProfile(round(statistics.median(lines)), threshold, len(cues), len(multiline),
                         statistics.median(c['end_ms'] - c['start_ms'] for c in cues))


def wrap_text(text: str, profile: LayoutProfile, config: dict | None = None) -> str:
    if '\n' in text or len(text) < profile.wrap_threshold_chars:
        return text
    from cutdeck.words import timed_tokens
    from transcribe.thai.atoms import default_lexicon, glue_atoms

    _, timed = timed_tokens([(text, 0, 1, None)])
    atoms = glue_atoms(timed, default_lexicon(config))
    choices = []
    for atom in atoms[1:]:
        pos = atom[4]
        left, right = text[:pos].rstrip(), text[pos:].lstrip()
        if not left or not right:
            continue
        over = max(0, len(left) - profile.target_line_chars) ** 2
        over += max(0, len(right) - profile.target_line_chars) ** 2
        cost = over * 4 + abs(len(left) - len(right))
        if text[pos - 1:pos].isspace() or text[pos:pos + 1].isspace():
            cost -= 6
        choices.append((cost, pos, left, right))
    if not choices:
        return text  # an unsplittable name/term stays intact
    _, _, left, right = min(choices)
    return left + '\n' + right


def layout_cues(cues: list[dict], profile: LayoutProfile, config: dict | None = None) -> list[dict]:
    return [{**c, 'text': wrap_text(c['text'], profile, config)} for c in cues]
