$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
& $VivadoBat -mode batch -nojournal -nolog -source (Join-Path $PSScriptRoot 'probe_tools.tcl')
if ($LASTEXITCODE -ne 0) { throw 'KV260 Vivado inventory failed' }
