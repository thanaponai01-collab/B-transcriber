#!/usr/bin/env bash
# convert_model.sh — one-time conversion of a Thai Whisper checkpoint to the
# CTranslate2 format faster-whisper needs. Run this ONCE per model; afterwards
# the engine just loads the output dir named in config.yaml (engine_a_model).
#
# Default: Typhoon Whisper Turbo — Large-v3 Turbo arch (4 decoder layers vs 32),
# ~11k h normalized Thai, offline-tuned, MIT. Smaller + faster than full
# Large-v3, which is the right trade on an 8GB 3070.
#
# Usage:
#   bash scripts/convert_model.sh                     # Typhoon Turbo (default)
#   bash scripts/convert_model.sh MONSOON             # YouTube-tuned fallback
#   bash scripts/convert_model.sh scb10x/some-model my-out-dir
set -euo pipefail

ARG1="${1:-TYPHOON_TURBO}"
case "$ARG1" in
  TYPHOON_TURBO) MODEL="scb10x/typhoon-whisper-turbo"; OUT="models/typhoon-whisper-turbo-ct2" ;;
  MONSOON)       MODEL="scb10x/monsoon-whisper-medium-gigaspeech2"; OUT="models/monsoon-whisper-medium-ct2" ;;
  *)             MODEL="$ARG1"; OUT="${2:-models/$(basename "$ARG1")-ct2}" ;;
esac

echo "Converting:  $MODEL"
echo "Output dir:  $OUT"

if [ -d "$OUT" ]; then
  echo "ERROR: $OUT already exists. Delete it first to re-convert." >&2
  exit 1
fi

# ct2-transformers-converter ships with ctranslate2[transformers].
if ! command -v ct2-transformers-converter >/dev/null 2>&1; then
  echo "Installing converter (ctranslate2 + transformers) ..."
  pip install "transformers[torch]>=4.23" "ctranslate2>=4.0" --break-system-packages \
    2>/dev/null || pip install "transformers[torch]>=4.23" "ctranslate2>=4.0"
fi

mkdir -p models
ct2-transformers-converter \
  --model "$MODEL" \
  --output_dir "$OUT" \
  --copy_files tokenizer.json preprocessor_config.json \
  --quantization float16

echo
echo "Done. Point config.yaml at it:"
echo "    engine_a_model: $OUT"
echo
echo "If load OOMs at float16 on the 3070, set in config.yaml:"
echo "    compute_type: int8_float16"
