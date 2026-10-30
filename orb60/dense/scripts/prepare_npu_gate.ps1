param([string]$Distribution = 'Ubuntu-20.04', [switch]$AssetsOnly)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
$denseBuild = Join-Path $ProjectRoot 'orb60/build/dense'
$assets = Join-Path $denseBuild 'assets'
New-Item -ItemType Directory -Force -Path $assets | Out-Null
& $ProjectPython (Join-Path $PSScriptRoot 'fetch_assets.py') --output $assets
if ($LASTEXITCODE -ne 0) { throw 'Official asset preparation failed' }
if ($AssetsOnly) { exit 0 }
$wslExe = Join-Path $env:SystemRoot 'System32/wsl.exe'
$linuxAssets = (& $wslExe -d $Distribution --exec wslpath -a $assets).Trim()
$linuxScript = (& $wslExe -d $Distribution --exec wslpath -a (Join-Path $PSScriptRoot 'bootstrap_conversion.sh')).Trim()
$linuxHome = (& $wslExe -d $Distribution --exec printenv HOME).Trim()
$conversionEnv = "$linuxHome/.local/share/orb60/dense-conversion-2.5.0-py310"
& $wslExe -d $Distribution --exec bash $linuxScript $linuxAssets $conversionEnv
if ($LASTEXITCODE -ne 0) { throw 'Private conversion environment failed' }
@{ distribution=$Distribution; assets=$linuxAssets; python="$conversionEnv/bin/python" } |
    ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $denseBuild 'conversion.local.json')
