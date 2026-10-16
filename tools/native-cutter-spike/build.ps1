param([string]$SdkRoot = '', [switch]$Test)
$ErrorActionPreference = 'Stop'
if (-not $SdkRoot) { $SdkRoot = Join-Path $PSScriptRoot '..\..\files\Premiere Pro 26.0 C++ SDK' }
$SdkRoot = (Resolve-Path -LiteralPath $SdkRoot).Path
$header = Join-Path $SdkRoot 'Examples\Headers\adobesdk\controlsurface\host\ControlSurfaceHostCommandSuite.h'
if (-not (Test-Path -LiteralPath $header)) { throw 'Adobe Control Surface host-command header is missing' }
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path -LiteralPath $vswhere)) { throw 'Microsoft C++ Build Tools are not installed' }
$msbuild = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -find 'MSBuild\**\Bin\MSBuild.exe'
if (-not $msbuild) { throw 'No MSBuild installation with the C++ toolchain was found' }
& ($msbuild | Select-Object -First 1) (Join-Path $PSScriptRoot 'CutterProbe.vcxproj') /nologo /m:1 /t:Build /p:Configuration=Release /p:Platform=x64 "/p:SdkRoot=$SdkRoot" "/p:Harness=$($Test.IsPresent.ToString().ToLowerInvariant())" /verbosity:minimal
if ($LASTEXITCODE -ne 0) { throw "Native spike build failed: $LASTEXITCODE" }
