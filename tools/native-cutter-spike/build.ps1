param([string]$SdkRoot = '', [switch]$Test)
$ErrorActionPreference = 'Stop'
if (-not $SdkRoot) {
  # The newest owner-supplied SDK under files/ (26.0 until 2026-11-21, then 27.0).
  $SdkRoot = Get-ChildItem -Directory (Join-Path $PSScriptRoot '..\..\files') -Filter 'Premiere Pro * C++ SDK' |
    Sort-Object { [version]($_.Name -replace '^Premiere Pro ([\d.]+) C\+\+ SDK$', '$1') } |
    Select-Object -Last 1 -ExpandProperty FullName
  if (-not $SdkRoot) { throw 'No Premiere Pro C++ SDK folder under files/' }
}
$SdkRoot = (Resolve-Path -LiteralPath $SdkRoot).Path
$header = Join-Path $SdkRoot 'Examples\Headers\adobesdk\controlsurface\host\ControlSurfaceHostCommandSuite.h'
if (-not (Test-Path -LiteralPath $header)) { throw 'Adobe Control Surface host-command header is missing' }
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path -LiteralPath $vswhere)) { throw 'Microsoft C++ Build Tools are not installed' }
$msbuild = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -find 'MSBuild\**\Bin\MSBuild.exe'
if (-not $msbuild) { throw 'No MSBuild installation with the C++ toolchain was found' }
& ($msbuild | Select-Object -First 1) (Join-Path $PSScriptRoot 'CutterProbe.vcxproj') /nologo /m:1 /t:Build /p:Configuration=Release /p:Platform=x64 "/p:SdkRoot=$SdkRoot" "/p:Harness=$($Test.IsPresent.ToString().ToLowerInvariant())" /verbosity:minimal
if ($LASTEXITCODE -ne 0) { throw "Native spike build failed: $LASTEXITCODE" }
