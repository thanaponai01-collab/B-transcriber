"""Phase C step 3 — LoRA fine-tune of the Phase B winner (HANDOFF_ONE_ENGINE.md
Section 5 item 3): HF `transformers` + `peft` LoRA on
`biodatlab/whisper-th-medium-combined`, the named fine-tuning base checkpoint
(TODO_LEDGER.md, Phase B). Recipe per the handoff's arXiv 2604.06507 lineage:
LoRA on `q_proj, v_proj, out_proj, fc1, fc2`, first ~3 encoder layers frozen
(excluded from adapter injection), ~5% trainable params.

**Data floor, enforced, not advisory.** The handoff is explicit: gains become
reliably large past ~800 utterances / ~60-90 min of corrected audio, and a
run below that is "collect, don't train yet." This script therefore refuses
to run for real (writes no checkpoint) when the manifest is below
`MIN_COLLECT_MINUTES`, unless `--dry-run` is passed. A dry run trains a
couple of steps purely to prove the LoRA/data/save pipeline is wired
end-to-end and tags its output `DRY_RUN` — it is never a real Phase C
candidate and must never be pushed through the eval harness.

    # wiring-proof only (small manifest, e.g. one recut clip)
    python -m tools.finetune_lora --dry-run

    # a real training run, once tools/make_finetune_set.py stats clears the floor
    python -m tools.finetune_lora --epochs 4

Output is a saved PEFT adapter (`output_dir/`), not yet merged or CT2-
converted — `merge_and_unload()` + `ct2-transformers-converter` (handoff
Section 5's "zero adapter code changes" pipeline) is a separate, later step
once a real run's adapter is worth promoting.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_MANIFEST = _ROOT / "transcribe" / "finetune" / "manifest.jsonl"
_DEFAULT_BASE_MODEL = "biodatlab/whisper-th-medium-combined"
_DEFAULT_OUTPUT_DIR = _ROOT / "transcribe" / "finetune" / "lora_out"

_TARGET_MODULES = ["q_proj", "v_proj", "out_proj", "fc1", "fc2"]
_FREEZE_ENCODER_LAYERS = 3


# ── manifest -> dataset ─────────────────────────────────────────────────────────

def load_manifest(manifest: Path) -> list[dict]:
    if not manifest.exists():
        raise FileNotFoundError(f"{manifest} not found - run tools/make_finetune_set.py first")
    entries = [json.loads(ln) for ln in manifest.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not entries:
        raise ValueError(f"{manifest} is empty - nothing to train on")
    return entries


def build_dataset(entries: list[dict], processor, sampling_rate: int = 16000):
    from datasets import Dataset

    def _load(example):
        import soundfile as sf
        audio, sr = sf.read(str(_ROOT / example["audio"]) if not Path(example["audio"]).is_absolute()
                             else example["audio"])
        if sr != sampling_rate:
            import librosa
            audio = librosa.resample(audio.astype("float32"), orig_sr=sr, target_sr=sampling_rate)
        features = processor.feature_extractor(audio, sampling_rate=sampling_rate).input_features[0]
        labels = processor.tokenizer(example["text"]).input_ids
        return {"input_features": features, "labels": labels}

    ds = Dataset.from_list(entries)
    return ds.map(_load, remove_columns=ds.column_names)


class DataCollator:
    """Pads `input_features` and `labels`; label pad positions become -100 so
    the Whisper loss ignores them (standard Seq2Seq-with-padding recipe)."""

    def __init__(self, processor):
        self.processor = processor

    def __call__(self, batch: list[dict]) -> dict:
        input_features = [{"input_features": b["input_features"]} for b in batch]
        batch_inputs = self.processor.feature_extractor.pad(input_features, return_tensors="pt")
        label_features = [{"input_ids": b["labels"]} for b in batch]
        labels_batch = self.processor.tokenizer.pad(label_features, return_tensors="pt")
        labels = labels_batch["input_ids"].masked_fill(labels_batch.attention_mask.ne(1), -100)
        batch_inputs["labels"] = labels
        return batch_inputs


# ── LoRA model ────────────────────────────────────────────────────────────────

def build_exclude_regex(freeze_encoder_layers: int) -> str | None:
    """Regex (peft `exclude_modules`, matched via `re.fullmatch`) excluding the
    first N encoder layers from LoRA injection - freezing them, per the
    handoff's recipe. Enumerates exact indices rather than a char-class range
    so it is correct for any layer count, not just single digits."""
    if freeze_encoder_layers <= 0:
        return None
    indices = "|".join(str(i) for i in range(freeze_encoder_layers))
    return rf"model\.encoder\.layers\.({indices})\..*"


def build_lora_model(
    base_model_id: str = _DEFAULT_BASE_MODEL,
    freeze_encoder_layers: int = _FREEZE_ENCODER_LAYERS,
    r: int = 8,
    alpha: int = 16,
    dropout: float = 0.05,
):
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForSpeechSeq2Seq

    model = AutoModelForSpeechSeq2Seq.from_pretrained(base_model_id, low_cpu_mem_usage=True)
    config = LoraConfig(
        r=r,
        lora_alpha=alpha,
        lora_dropout=dropout,
        target_modules=_TARGET_MODULES,
        exclude_modules=build_exclude_regex(freeze_encoder_layers),
        bias="none",
    )
    return get_peft_model(model, config)


def count_trainable_params(model) -> dict:
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    return {"trainable_params": trainable, "total_params": total,
            "trainable_pct": round(100 * trainable / total, 3) if total else 0.0}


# ── data-floor guard ────────────────────────────────────────────────────────────

def check_data_sufficiency(manifest: Path, dry_run: bool) -> None:
    """Refuse a non-dry-run below the handoff's MIN_COLLECT_MINUTES floor.
    Raises ValueError (caller turns this into a clean CLI refusal) rather than
    silently training on statistically meaningless data."""
    if dry_run:
        return
    from tools.make_finetune_set import MIN_COLLECT_MINUTES, compute_stats
    stats = compute_stats(manifest)
    if stats["total_minutes"] < MIN_COLLECT_MINUTES:
        raise ValueError(
            f"manifest has only {stats['total_minutes']} min, below the "
            f"{MIN_COLLECT_MINUTES} min floor (HANDOFF_ONE_ENGINE.md Section 5) - "
            "pass --dry-run for a wiring-proof run only, or collect more data first"
        )


# ── train ─────────────────────────────────────────────────────────────────────

def train(
    manifest: Path = _DEFAULT_MANIFEST,
    base_model: str = _DEFAULT_BASE_MODEL,
    output_dir: Path = _DEFAULT_OUTPUT_DIR,
    epochs: float = 3.0,
    lr: float = 1e-4,
    batch_size: int = 2,
    freeze_encoder_layers: int = _FREEZE_ENCODER_LAYERS,
    dry_run: bool = False,
) -> dict:
    check_data_sufficiency(manifest, dry_run)
    entries = load_manifest(manifest)

    from transformers import AutoProcessor, Seq2SeqTrainer, Seq2SeqTrainingArguments
    import torch

    processor = AutoProcessor.from_pretrained(base_model)
    dataset = build_dataset(entries, processor)
    model = build_lora_model(base_model, freeze_encoder_layers=freeze_encoder_layers)
    param_stats = count_trainable_params(model)

    training_args = Seq2SeqTrainingArguments(
        output_dir=str(output_dir),
        per_device_train_batch_size=batch_size,
        num_train_epochs=1 if dry_run else epochs,
        max_steps=2 if dry_run else -1,
        learning_rate=lr,
        logging_steps=1,
        save_strategy="no",
        report_to=[],
        fp16=torch.cuda.is_available(),
        remove_unused_columns=False,
        label_names=["labels"],
    )
    trainer = Seq2SeqTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=DataCollator(processor),
    )
    result = trainer.train()

    output_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(output_dir))
    if dry_run:
        (output_dir / "DRY_RUN.md").write_text(
            "Wiring-proof dry run (HANDOFF_ONE_ENGINE.md Phase C step 3), trained on "
            f"{len(entries)} utterances - far below the data floor. Do NOT gate this "
            "checkpoint or treat it as a real Phase C candidate; re-run without --dry-run "
            "once tools/make_finetune_set.py stats clears MIN_COLLECT_MINUTES.",
            encoding="utf-8",
        )

    return {
        "n_utterances": len(entries),
        "final_loss": result.training_loss,
        "output_dir": str(output_dir),
        "dry_run": dry_run,
        **param_stats,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=str(_DEFAULT_MANIFEST))
    ap.add_argument("--base-model", default=_DEFAULT_BASE_MODEL)
    ap.add_argument("--output-dir", default=str(_DEFAULT_OUTPUT_DIR))
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--batch-size", type=int, default=2)
    ap.add_argument("--freeze-encoder-layers", type=int, default=_FREEZE_ENCODER_LAYERS)
    ap.add_argument("--dry-run", action="store_true",
                     help="wiring-proof run only: caps to 2 steps, tags output DRY_RUN, "
                          "bypasses the data-floor guard")
    args = ap.parse_args()

    try:
        result = train(
            manifest=Path(args.manifest),
            base_model=args.base_model,
            output_dir=Path(args.output_dir),
            epochs=args.epochs,
            lr=args.lr,
            batch_size=args.batch_size,
            freeze_encoder_layers=args.freeze_encoder_layers,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"[finetune_lora] REFUSED: {e}")
        raise SystemExit(1)

    tag = "DRY RUN " if result["dry_run"] else ""
    print(f"[finetune_lora] {tag}done: {result['n_utterances']} utterances, "
          f"{result['trainable_params']}/{result['total_params']} params trainable "
          f"({result['trainable_pct']}%), final_loss={result['final_loss']:.4f}")
    print(f"[finetune_lora] adapter saved to {result['output_dir']}")
    if result["dry_run"]:
        print("[finetune_lora] DRY RUN - not a real candidate, do not gate this checkpoint")


if __name__ == "__main__":
    main()
