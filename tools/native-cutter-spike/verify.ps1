$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$output = Join-Path $repo 'output\native-cutter-spike'
& (Join-Path $PSScriptRoot 'build.ps1')
& (Join-Path $PSScriptRoot 'build.ps1') -Test
# The harness redirects TMP here, so its requests never reach a running Premiere's folder.
$scratch = Join-Path $output 'harness-temp'
if (Test-Path -LiteralPath $scratch) { Remove-Item -LiteralPath $scratch -Recurse -Force }
New-Item -ItemType Directory -Path $scratch | Out-Null
$dumpRoot = Join-Path $scratch 'CutDeckCutterSpike'
$transcript = & (Join-Path $output 'CutterProbeHarness.exe') (Join-Path $output 'CutDeckCutterProbe.acsrf') $scratch 2>&1
if ($LASTEXITCODE -ne 0) { throw ($transcript -join "`n") }
$transcript | Set-Content -LiteralPath (Join-Path $output 'harness-proof.txt') -Encoding utf8
$files = @(Get-ChildItem -LiteralPath $dumpRoot -Filter 'commands-*.json' -File)
# Four catalog scenarios connect, plus eleven request scenarios that each finish a full catalog first.
if ($files.Count -ne 15) { throw "Expected fifteen synthetic catalogs; got $($files.Count)" }
$reports = @($files | ForEach-Object {
    $record = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
    if ($record.mode -ne 'read-only' -or $record.commands.Count -ne $record.examinedCommands) { throw 'Catalog coverage or mode differs from rows' }
    [pscustomobject]@{ path = $_.FullName; reported = $record.reportedCommands; examined = $record.examinedCommands; complete = $record.complete; errors = $record.errors }
})
$normal = @($reports | Where-Object { $_.complete -and $_.reported -eq 130 -and $_.examined -eq 130 -and $_.errors -eq 0 })
if ($normal.Count -ne 12) { throw 'Full enumeration did not complete in every connected scenario' }
if (@($reports | Where-Object { -not $_.complete -and $_.errors -eq 1 -and $_.examined -eq 130 }).Count -ne 1) { throw 'Failed SDK row was hidden' }
if (@($reports | Where-Object { -not $_.complete -and $_.examined -eq 64 }).Count -ne 1) { throw 'Early disconnect did not retain partial coverage' }
if (@($reports | Where-Object { $_.complete -and $_.reported -eq 0 -and $_.examined -eq 0 }).Count -ne 1) { throw 'Empty catalog failed' }
$full = Get-Content -LiteralPath $normal[0].path -Raw -Encoding UTF8 | ConvertFrom-Json
if ($full.commands[3].commandID -ne 'cmd.sequence.razorateditline.all' -or -not $full.commands[3].commandName.EndsWith('ก')) { throw 'Command identity or UTF-8 label was lost' }
if (@(Get-ChildItem -LiteralPath $dumpRoot -Filter 'request-*' -File).Count -ne 0) { throw 'A request file was left behind' }
$reports | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output 'harness-proof.json') -Encoding utf8
$transcript
$reports | Format-Table reported, examined, complete, errors
Write-Output 'PASS native loader and synthetic SDK host checks; real Premiere behavior remains a separate gate.'
