"""Unit tests for cutdeck.xml_sync — XML multi-camera alignment and layer simplification."""

from pathlib import Path
from xml.etree import ElementTree as ET
import numpy as np
import pytest

from cutdeck.contracts import Timebase
from cutdeck.xml_sync import sync_sequence_xml


SAMPLE_XML_PATH = Path(__file__).parent / "fixtures" / "cutdeck_recut_sample_scrubbed.xml"


# Deterministic non-periodic master signal simulating real acoustic speech/ambient recording
_RND = np.random.RandomState(42)
_MASTER_DUR = 2000.0  # seconds
_SR = 16000
_RAW_NOISE = _RND.randn(int(_MASTER_DUR * _SR)).astype(np.float32)
# Low-pass filter to speech bandwidth
_KERNEL = np.ones(8, dtype=np.float32) / 8.0
_MASTER_AUDIO = np.convolve(_RAW_NOISE, _KERNEL, mode="same")


def mock_audio_generator(duration_s: float, offset_s: float = 0.0, sr: int = 16000) -> np.ndarray:
    """Extract audio slice from the master signal at the specified offset."""
    start_idx = int(offset_s * sr)
    length = int(duration_s * sr)
    if start_idx < 0 or start_idx + length > len(_MASTER_AUDIO):
        return np.zeros(length, dtype=np.float32)
    return _MASTER_AUDIO[start_idx : start_idx + length]


def test_sync_sequence_xml_retiming():
    """Test full multi-camera XML sync with known synthetic audio offsets."""
    with open(SAMPLE_XML_PATH, "r", encoding="utf-8") as f:
        source_xml = f.read()

    # File offsets:
    # angle1 (ref): starts at t=10.0s
    # angle2: starts at t=15.0s (i.e. 5.0s after ref -> offset = +5.0s = 150 frames @ 30fps)
    # angle3: starts at t=8.0s (i.e. 2.0s before ref -> offset = -2.0s = -60 frames @ 30fps)
    def mock_extractor(file_path, start_s=None, duration_s=None, sample_rate=16000):
        name = Path(file_path).name
        dur = duration_s or 30.0
        start = start_s or 0.0
        if "angle1" in name:
            return mock_audio_generator(dur, offset_s=10.0 + start, sr=sample_rate)
        elif "angle2" in name:
            return mock_audio_generator(dur, offset_s=15.0 + start, sr=sample_rate)
        elif "angle3" in name:
            return mock_audio_generator(dur, offset_s=8.0 + start, sr=sample_rate)
        return np.zeros(int(dur * sample_rate), dtype=np.float32)

    synced_xml, report = sync_sequence_xml(
        source_xml,
        ref_track_idx=0,
        audio_extractor=mock_extractor,
    )

    assert report.sequence_name.endswith("_Synced")
    assert report.total_groups == 3
    assert report.synced_groups == 3
    assert report.unsynced_groups == 0

    # Because angle3 started 2.0s (-60 frames) before reference,
    # the entire sequence should be shifted so angle3 starts at frame 0,
    # and angle1 (reference) starts at frame 60!
    # And angle2 (started 5.0s after ref = 150 frames after ref) starts at frame 60 + 150 = 210!
    root = ET.fromstring(synced_xml)
    seq = root.find("sequence")
    assert seq is not None

    # Check video clipitems start frames
    clips = {}
    for track in seq.findall("media/video/track"):
        for clip in track.findall("clipitem"):
            f_id = clip.find("file").get("id")
            clips[f_id] = int(clip.find("start").text)

    assert clips["file-3"] == 0   # Earliest angle starts at 0
    assert clips["file-1"] == 60  # Reference angle shifted by +60
    assert clips["file-2"] == 210 # Angle 2 at 60 + 150 = 210


def test_sync_sequence_layer_simplification():
    """Verify that empty video tracks and exploded redundant audio tracks are removed."""
    with open(SAMPLE_XML_PATH, "r", encoding="utf-8") as f:
        source_xml = f.read()

    def mock_extractor(file_path, start_s=None, duration_s=None, sample_rate=16000):
        dur = duration_s or 30.0
        return mock_audio_generator(dur, offset_s=10.0 + (start_s or 0.0), sr=sample_rate)

    synced_xml, _report = sync_sequence_xml(
        source_xml,
        ref_track_idx=0,
        audio_extractor=mock_extractor,
    )

    root = ET.fromstring(synced_xml)
    video_tracks = root.findall("sequence/media/video/track")
    audio_tracks = root.findall("sequence/media/audio/track")

    # In original sample XML:
    # 5 video tracks (tracks 4 and 5 were empty)
    # Empty video tracks should have been removed!
    assert len(video_tracks) == 3

    # Audio tracks: in sample XML file-1 has 8 channels, file-2 has 2, file-3 has 2 (12 total).
    # All 12 audio tracks must be preserved!
    assert len(audio_tracks) == 12

    # Verify that stereo tracks are properly paired with exploded track indices 0 and 1,
    # and output channel indices 1 and 2, so Premiere Pro collapses them into stereo timeline tracks.
    for i in range(0, len(audio_tracks), 2):
        t0 = audio_tracks[i]
        t1 = audio_tracks[i + 1]
        assert t0.attrib.get("currentExplodedTrackIndex") == "0"
        assert t0.attrib.get("totalExplodedTrackCount") == "2"
        assert t0.attrib.get("premiereTrackType") == "Stereo"
        assert t0.findtext("outputchannelindex") == "1"

        assert t1.attrib.get("currentExplodedTrackIndex") == "1"
        assert t1.attrib.get("totalExplodedTrackCount") == "2"
        assert t1.attrib.get("premiereTrackType") == "Stereo"
        assert t1.findtext("outputchannelindex") == "2"

    # Verify that clipitem <link> elements have their trackindex updated to match new track positions
    for t_idx, track in enumerate(audio_tracks, start=1):
        for clip in track.findall("clipitem"):
            for link in clip.findall("link"):
                ref_id = link.findtext("linkclipref")
                if ref_id == clip.get("id"):
                    assert int(link.findtext("trackindex")) == t_idx


def test_sync_sequence_unsynced_placement_at_end():
    """Verify that an unsynced clip is placed after the synced timeline."""
    with open(SAMPLE_XML_PATH, "r", encoding="utf-8") as f:
        source_xml = f.read()

    # Angle 2 is completely silent -> unsynced
    def mock_extractor(file_path, start_s=None, duration_s=None, sample_rate=16000):
        name = Path(file_path).name
        dur = duration_s or 30.0
        if "angle2" in name:
            return np.zeros(int(dur * sample_rate), dtype=np.float32)  # silent!
        return mock_audio_generator(dur, offset_s=10.0 + (start_s or 0.0), sr=sample_rate)

    synced_xml, report = sync_sequence_xml(
        source_xml,
        ref_track_idx=0,
        audio_extractor=mock_extractor,
    )

    assert report.synced_groups == 2
    assert report.unsynced_groups == 1
    assert "angle2" in str(report.unsynced_reasons)

    root = ET.fromstring(synced_xml)
    clips = {}
    for track in root.findall("sequence/media/video/track"):
        for clip in track.findall("clipitem"):
            f_id = clip.find("file").get("id")
            clips[f_id] = (int(clip.find("start").text), int(clip.find("end").text))

    # Synced clips end before the unsynced clip starts
    synced_end = max(clips["file-1"][1], clips["file-3"][1])
    unsynced_start = clips["file-2"][0]
    assert unsynced_start >= synced_end + 60  # placed at end with gap buffer
