"""Unit tests for tools/finetune_lora.py (HANDOFF_ONE_ENGINE.md Phase C step 3).

Covers the parts that don't require loading real model weights: the manifest
loader, the LoRA layer-freeze regex, the data collator's padding contract, and
the data-floor guard. The actual model/LoRA/Trainer wiring is proven by a
manual `--dry-run` invocation (documented in TODO_LEDGER.md), matching this
repo's convention of never loading heavy ASR checkpoints inside pytest
(faster_whisper/qwen3_asr adapters are tested the same way, against pure
helper functions, not real weights)."""

import json
import re
import tempfile
from pathlib import Path

import pytest
import torch
from transformers.feature_extraction_utils import BatchFeature
from transformers.tokenization_utils_base import BatchEncoding

from tools.finetune_lora import (
    DataCollator,
    build_exclude_regex,
    check_data_sufficiency,
    load_manifest,
)


# ── manifest loading ──────────────────────────────────────────────────────────

def test_load_manifest_reads_jsonl_lines():
    d = Path(tempfile.mkdtemp())
    manifest = d / "manifest.jsonl"
    manifest.write_text(
        json.dumps({"audio": "a.wav", "text": "hi", "duration_ms": 1000}) + "\n"
        + json.dumps({"audio": "b.wav", "text": "there", "duration_ms": 1500}) + "\n",
        encoding="utf-8",
    )
    entries = load_manifest(manifest)
    assert len(entries) == 2
    assert entries[0]["text"] == "hi"


def test_load_manifest_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_manifest(Path(tempfile.mkdtemp()) / "does_not_exist.jsonl")


def test_load_manifest_empty_file_raises():
    d = Path(tempfile.mkdtemp())
    manifest = d / "manifest.jsonl"
    manifest.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        load_manifest(manifest)


# ── LoRA layer-freeze regex ───────────────────────────────────────────────────

def test_build_exclude_regex_matches_frozen_layers_only():
    pattern = build_exclude_regex(3)
    for i in range(3):
        assert re.fullmatch(pattern, f"model.encoder.layers.{i}.self_attn.q_proj")
    for i in range(3, 24):
        assert not re.fullmatch(pattern, f"model.encoder.layers.{i}.self_attn.q_proj")
    # decoder layers are never excluded by this pattern
    assert not re.fullmatch(pattern, "model.decoder.layers.0.self_attn.q_proj")


def test_build_exclude_regex_handles_double_digit_counts():
    pattern = build_exclude_regex(12)
    assert re.fullmatch(pattern, "model.encoder.layers.11.fc1")
    assert not re.fullmatch(pattern, "model.encoder.layers.12.fc1")
    # a naive char-class range ([0-11]) would wrongly match "layers.1" as a
    # prefix of "layers.11" or misparse the range - this guards against that class of bug
    assert not re.fullmatch(pattern, "model.encoder.layers.111.fc1")


def test_build_exclude_regex_zero_freezes_nothing():
    assert build_exclude_regex(0) is None


# ── data collator ─────────────────────────────────────────────────────────────

class _FakeFeatureExtractor:
    def pad(self, features, return_tensors="pt"):
        stacked = torch.stack([torch.tensor(f["input_features"]) for f in features])
        return BatchFeature({"input_features": stacked})


class _FakeTokenizer:
    def pad(self, features, return_tensors="pt"):
        ids = [f["input_ids"] for f in features]
        maxlen = max(len(i) for i in ids)
        padded = [i + [0] * (maxlen - len(i)) for i in ids]
        attn = [[1] * len(i) + [0] * (maxlen - len(i)) for i in ids]
        return BatchEncoding({
            "input_ids": torch.tensor(padded),
            "attention_mask": torch.tensor(attn),
        })


class _FakeProcessor:
    feature_extractor = _FakeFeatureExtractor()
    tokenizer = _FakeTokenizer()


def test_data_collator_pads_labels_and_masks_padding_with_minus_100():
    collator = DataCollator(_FakeProcessor())
    batch = [
        {"input_features": [1.0, 2.0], "labels": [10, 11, 12]},
        {"input_features": [3.0, 4.0], "labels": [20, 21]},
    ]
    out = collator(batch)
    assert out["input_features"].shape == (2, 2)
    assert out["labels"].tolist() == [[10, 11, 12], [20, 21, -100]]


# ── data-floor guard ──────────────────────────────────────────────────────────

def test_check_data_sufficiency_dry_run_always_passes():
    check_data_sufficiency(Path(tempfile.mkdtemp()) / "nonexistent.jsonl", dry_run=True)


def test_check_data_sufficiency_refuses_thin_manifest_when_not_dry_run():
    d = Path(tempfile.mkdtemp())
    manifest = d / "manifest.jsonl"
    manifest.write_text(
        json.dumps({"duration_ms": 60_000, "source": "x"}) + "\n",  # 1 min, well below floor
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="below the"):
        check_data_sufficiency(manifest, dry_run=False)


def test_check_data_sufficiency_allows_sufficient_manifest():
    d = Path(tempfile.mkdtemp())
    manifest = d / "manifest.jsonl"
    lines = [json.dumps({"duration_ms": 60_000, "source": "x"}) for _ in range(50)]  # 50 min
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    check_data_sufficiency(manifest, dry_run=False)  # must not raise
