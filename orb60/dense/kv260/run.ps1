param([ValidateSet('Bootstrap','Host','Toolchain','CompileDiagnostic','QuantizedReplay','Package')][string]$Stage='Host',
      [ValidateSet('midas','fastdepth')][string]$Family='fastdepth', [string]$Distribution='Ubuntu-20.04')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
if ($Stage -eq 'Package') {
    Push-Location $ProjectRoot
    try { & $ProjectPython -m orb60.dense.kv260.package --root $ProjectRoot } finally { Pop-Location }
} else {
    $linuxRoot=& wsl -d $Distribution --exec wslpath -a $ProjectRoot
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($linuxRoot)) { throw 'Cannot resolve workspace in WSL' }
    $linuxRoot=$linuxRoot.Trim()
    $extra=@()
    $script = switch ($Stage) {
        'Bootstrap' {'bootstrap_host.sh'}
        'Host' { if ($Family -eq 'fastdepth') {'fastdepth/run_host.sh'} else {'run_host.sh'} }
        'Toolchain' { $extra=@($(if ($Family -eq 'fastdepth') {'fastdepth/toolchain.sh'} else {'toolchain.sh'})); 'run_toolchain.sh' }
        'CompileDiagnostic' { $extra=@($(if ($Family -eq 'fastdepth') {'fastdepth/compile.sh'} else {'run_diagnostic_compile.sh'})); 'run_toolchain.sh' }
        'QuantizedReplay' { $extra=@($(if ($Family -eq 'fastdepth') {'fastdepth/quantized_replay.sh'} else {'run_quantized_replay.sh'})); 'run_toolchain.sh' }
    }
    & wsl -d $Distribution --exec bash "$linuxRoot/orb60/dense/kv260/$script" @extra
}
if ($LASTEXITCODE -ne 0) { throw "KV260 stage $Stage failed ($LASTEXITCODE); retain the log/report." }
