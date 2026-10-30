param([ValidateSet('create','verify','open')][string]$Action='open')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'project_env.ps1')
$booleanRoot=Join-Path $ProjectRoot 'boolean_vivado'
$booleanScratch=Join-Path $VivadoBuildRoot 'boolean_exam'
New-Item -ItemType Directory -Force $booleanScratch | Out-Null
$booleanProject=Join-Path $booleanRoot 'project\boolean_exam.xpr'
if($Action -eq 'open') {
    if(-not (Test-Path -LiteralPath $booleanProject)){throw 'Create the project first: scripts/boolean_vivado.ps1 -Action create'}
    Start-Process -FilePath $VivadoBat -ArgumentList @('-mode','gui',('"'+$booleanProject+'"')) -WorkingDirectory $booleanScratch -WindowStyle Hidden
    exit 0
}
$booleanScript=if($Action -eq 'verify'){'verify_project.tcl'}else{'create_project.tcl'}
Push-Location $booleanScratch
try {
    & $VivadoBat -mode batch -source (Join-Path $booleanRoot ('scripts\'+$booleanScript)) -log ($Action+'.log') -journal ($Action+'.jou')
    if($LASTEXITCODE -ne 0){throw "Vivado $Action failed: $LASTEXITCODE"}
} finally {Pop-Location}
