param(
    [ValidateSet('install-evo','extract','validate','transfer','run','summary','report')][string]$Action,
    [string]$Archive,
    [string]$Batch = 'MH01_600x350_01',
    [string]$CoolingNote
)
$ErrorActionPreference = 'Stop'
$ExperimentRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $ExperimentRoot '..\..\scripts\project_env.ps1')
$dataset = Join-Path $ProjectRoot 'data\euroc\MH_01_easy'
$report = Join-Path $ExperimentRoot 'reports\a2'
New-Item -ItemType Directory -Force $report | Out-Null
switch ($Action) {
    'install-evo' {
        $installLog = Join-Path $report 'evo-pc-install.log'
        & $ProjectPython -m ensurepip --default-pip *> $installLog
        if ($LASTEXITCODE -ne 0) { Get-Content $installLog -Tail 6; exit $LASTEXITCODE }
        & $ProjectPython -m pip install --disable-pip-version-check --index-url https://pypi.tuna.tsinghua.edu.cn/simple --retries 1 --timeout 15 evo *>> $installLog
        if ($LASTEXITCODE -ne 0) { Get-Content $installLog -Tail 6; exit $LASTEXITCODE }
        & $ProjectPython -m pip freeze > (Join-Path $report 'evo-pc-requirements.txt')
        & $ProjectPython -c 'import evo; print("PC_EVO_INSTALLED " + evo.__version__)'
    }
    'extract' {
        if (-not $Archive) { $Archive = Join-Path $ProjectRoot 'MH_01_easy.zip' }
        & $ProjectPython (Join-Path $PSScriptRoot 'prepare_dataset_a2.py') $Archive --output $dataset
    }
    'validate' {
        & $ProjectPython (Join-Path $PSScriptRoot 'validate_mh01.py') $dataset --timestamps (Join-Path $report 'MH01.txt') --output (Join-Path $report 'dataset_pc')
    }
    'transfer' {
        $board = Get-Content -Raw (Join-Path $ExperimentRoot 'local_board.json') | ConvertFrom-Json
        $alias = if ($board.sshAlias) { $board.sshAlias } else { 'rk3588' }
        if ($alias -notmatch '^[A-Za-z0-9_.-]+$' -or $alias.StartsWith('-')) { throw 'Invalid SSH alias' }
        & $ProjectPython (Join-Path $PSScriptRoot 'validate_mh01.py') $dataset --timestamps (Join-Path $report 'MH01.txt') --output (Join-Path $report 'dataset_pc')
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & ssh -o BatchMode=yes $alias 'mkdir -p ~/data/euroc'
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & scp -q -r $dataset "${alias}:data/euroc/"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & (Join-Path $PSScriptRoot 'rk.ps1') exec 'bash scripts/prepare_a2.sh' -Name a2-prepare
    }
    'summary' {
        & $ProjectPython (Join-Path $PSScriptRoot 'summarize_a2.py') --batch $Batch
    }
    'report' {
        & $ProjectPython (Join-Path $PSScriptRoot 'report_a2.py') --batch $Batch
    }
    'run' {
        if (-not $CoolingNote) { throw 'CoolingNote must describe confirmed physical cooling' }
        $batchArgs = @('--dataset',$dataset,'--batch',$Batch,'--cooling-note',$CoolingNote)
        & $ProjectPython (Join-Path $PSScriptRoot 'batch_a2.py') @batchArgs
    }
}
exit $LASTEXITCODE
