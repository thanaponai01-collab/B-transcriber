<#
.SYNOPSIS
    Recut an exported FCP7 XML sequence: aggressive silence removal + ASR-protected
    short-speech islands. See docs/HANDOFF_CUTDECK_XML_RECUT.md and
    transcribe/config.aggressive_cut.yaml (tuned thresholds vs. transcribe/config.yaml).

.EXAMPLE
    scripts\cut_xml.ps1 "E:\path\to\sequence.xml"

    Writes "sequence_cut.xml" beside the input. No Premiere mixdown export needed —
    audio is auto-extracted from the XML's own source media.

.NOTES
    Runs a full ASR pass over the whole sequence's audio first (slower, but lets the
    min-clip merge tell real short words from noise instead of guessing). For a much
    faster silence-only pass (less accurate on short speech islands), drop -asr:
        python -m cutdeck.xml_recut $xml --config transcribe/config.yaml --overlay transcribe/config.aggressive_cut.yaml
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$SequenceXml,

    [string]$Config = "transcribe\config.yaml",

    [string]$Overlay = "transcribe\config.aggressive_cut.yaml",

    [switch]$NoAsr,

    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))

$argsList = @($SequenceXml, "--config", $Config, "--overlay", $Overlay)
if (-not $NoAsr) { $argsList += "--asr" }
if ($DryRun) { $argsList += "--dry-run" }

python -m cutdeck.xml_recut @argsList
