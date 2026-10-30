param(
    [ValidateSet('compile','sim','sim-case','all','image','debug','wave-vscode','wave-gtkwave')]
    [string]$Action = 'sim',
    [string]$File = '',
    [string]$Case = '',
    [string]$Image = '',
    [int]$MaxDim = 256
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $projectRoot 'scripts\project_env.ps1')
Set-Location $projectRoot

# Make VS Code tasks independent of the PATH inherited when VS Code started.
$toolDirectories = @(
    "$env:LOCALAPPDATA\oss-cad-suite\oss-cad-suite\bin"
) | Where-Object { Test-Path -LiteralPath $_ }
if ($toolDirectories.Count -gt 0) {
    $env:Path = (($toolDirectories -join ';') + ';' + $env:Path)
}
$env:PYTHONIOENCODING = 'utf-8'

$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) {
    $python = $venvPython
} else {
    $pythonCommand = Get-Command python -ErrorAction Stop
    $python = $pythonCommand.Source
}

function Find-Tool {
    param([string]$Name, [string[]]$Fallbacks = @())
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in $Fallbacks) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw "Required tool not found: $Name"
}

function Get-CaseFromFile {
    param([string]$CurrentFile)
    $normalized = $CurrentFile.ToLowerInvariant().Replace('/', '\')
    if ($normalized -match 'off_by_one|bug_math') { return 'bug_math' }
    if ($normalized -match 'bad_backpressure|bug_backpressure') {
        return 'bug_backpressure'
    }
    if ($normalized -match 'orb_hamming_matcher_bad_msb|bug_hamming') {
        return 'bug_hamming'
    }
    if ($normalized -match 'orb_hamming_matcher|test_orb_hamming') {
        return 'hamming'
    }
    if ($normalized -match 'axi_image_invert_dma|test_axi_dma') { return 'dma' }
    if ($normalized -match 'axi_ram|test_axi_ram') { return 'ram' }
    return 'axis'
}

function Invoke-Runner {
    param([string[]]$Arguments)
    & $python (Join-Path $projectRoot 'run.py') @Arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Get-LatestWave {
    param([string[]]$Extensions)
    $buildDirectory = Join-Path $projectRoot 'build'
    if (-not (Test-Path -LiteralPath $buildDirectory)) { return $null }
    return Get-ChildItem -LiteralPath $buildDirectory -Recurse -File |
        Where-Object { $Extensions -contains $_.Extension.ToLowerInvariant() } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

switch ($Action) {
    'compile' {
        if (-not $File -or -not (Test-Path -LiteralPath $File)) {
            throw 'Open a Verilog/SystemVerilog file before running compile.'
        }
        if ([System.IO.Path]::GetExtension($File) -notin '.v', '.sv') {
            throw 'The current file is not Verilog/SystemVerilog.'
        }
        $sourceText = Get-Content -LiteralPath $File -Raw
        $moduleMatch = [regex]::Match(
            $sourceText,
            '(?m)^\s*module\s+([A-Za-z_][A-Za-z0-9_]*)'
        )
        if (-not $moduleMatch.Success) { throw 'No module declaration found.' }
        $top = $moduleMatch.Groups[1].Value
        $outputDirectory = Join-Path $projectRoot 'build\vscode\compile'
        New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
        $output = Join-Path $outputDirectory ($top + '.vvp')
        $iverilog = Find-Tool 'iverilog' @(
            (Join-Path $IcarusBin 'iverilog.exe')
        )
        & $iverilog -g2012 -s $top -o $output $File
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Write-Host "COMPILE PASS -> $output"
    }
    'sim' {
        $chosenCase = Get-CaseFromFile $File
        Write-Host "[VS Code] selected test case: $chosenCase"
        Invoke-Runner @('--test', $chosenCase, '--vcd')
    }
    'sim-case' {
        if (-not $Case) { throw 'A simulation case is required.' }
        Invoke-Runner @('--test', $Case, '--vcd')
    }
    'all' {
        Invoke-Runner @('--test', 'all')
    }
    'image' {
        if (-not $Image -or -not (Test-Path -LiteralPath $Image)) {
            throw "Image not found: $Image"
        }
        if ($MaxDim -lt 1) { throw 'MaxDim must be positive.' }
        # Deliberately omit waves: a real image creates a very large VCD.
        Invoke-Runner @(
            '--test', 'axis', '--image', $Image,
            '--max-dim', $MaxDim.ToString()
        )
    }
    'debug' {
        & $python (Join-Path $projectRoot 'scripts\demo_debug.py')
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    'wave-vscode' {
        $wave = Get-LatestWave @('.vcd')
        if (-not $wave) {
            $fst = Get-LatestWave @('.fst')
            if (-not $fst) { throw 'No VCD/FST found. Run a wave simulation first.' }
            $converter = Find-Tool 'fst2vcd' @(
                (Join-Path $GtkWaveBin 'fst2vcd.exe')
            )
            $vcdPath = [System.IO.Path]::ChangeExtension($fst.FullName, '.vcd')
            & $converter -f $fst.FullName -o $vcdPath
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            $wave = Get-Item -LiteralPath $vcdPath
        }
        $code = Find-Tool 'code' @('D:\Microsoft VS Code\bin\code.cmd')
        Write-Host "Opening WaveTrace-compatible VCD: $($wave.FullName)"
        & $code --reuse-window $wave.FullName
        exit $LASTEXITCODE
    }
    'wave-gtkwave' {
        $wave = Get-LatestWave @('.fst', '.vcd')
        if (-not $wave) { throw 'No VCD/FST found. Run a wave simulation first.' }
        $gtkwave = Find-Tool 'gtkwave' @(
            (Join-Path $GtkWaveBin 'gtkwave.exe')
        )
        Write-Host "Opening GTKWave: $($wave.FullName)"
        Start-Process -FilePath $gtkwave -ArgumentList @($wave.FullName)
    }
}
