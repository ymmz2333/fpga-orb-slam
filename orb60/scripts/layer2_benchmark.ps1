[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$HlsJob)
. (Join-Path $PSScriptRoot 'environment.ps1')
$parent=[IO.Path]::GetFullPath($HlsJob)
$prior=Get-Content -LiteralPath (Join-Path $parent 'status.json') -Raw | ConvertFrom-Json
if ($prior.State -ne 'SUCCEEDED' -or !$prior.Cosim -or $prior.Kernel -ne 'layer2' -or $prior.PeriodNs -ne 10) {
    throw 'Requires accepted shared-layer 100 MHz C/RTL job'
}
$name='{0}_layer2_benchmark_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8))
$job=Join-Path $Orb60Root "build/optimized/benchmark/$name"
New-Item -ItemType Directory -Path $job | Out-Null
$state=[ordered]@{State='RUNNING';Stage='PREPARE';Job=$job;ParentHlsJob=$parent;StartedUtc=[DateTime]::UtcNow.ToString('o');ProcessId=$PID;Scope='Shared layer only; no descriptors/PS/physical DDR; no synthesis or route'}
$status=Join-Path $job 'status.json'
$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
Write-Output "ORB60_LAYER2_BENCH_JOB=$job"
function RtlManifest([string]$directory) {
    $items=@(Get-ChildItem -LiteralPath $directory -File | Sort-Object Name | ForEach-Object {
        [ordered]@{Name=$_.Name;SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}
    })
    if (!$items.Count) {throw 'Missing accepted synthesis RTL'}
    return ConvertTo-Json -InputObject $items -Depth 3
}
try {
    Copy-Item -LiteralPath (Join-Path $parent 'inputs') -Destination $job -Recurse
    Copy-Item -LiteralPath (Join-Path $Orb60Root 'optimized/FPGA_ORB_HLS/fastv2/next/hls/tb_layer2_benchmark.cpp') -Destination (Join-Path $job 'inputs/tb_layer2_benchmark.cpp')
    New-Item -ItemType Directory -Path (Join-Path $job 'projects') | Out-Null
    Copy-Item -LiteralPath (Join-Path $parent 'projects/layer2') -Destination (Join-Path $job 'projects/layer2') -Recurse
    $rtl=Join-Path $job 'projects/layer2/solution1/syn/verilog'
    $before=RtlManifest $rtl
    $before | Set-Content -LiteralPath (Join-Path $job 'rtl_manifest_before.json') -Encoding UTF8
    if ($before -ne (RtlManifest (Join-Path $parent 'projects/layer2/solution1/syn/verilog'))) {throw 'Copied RTL differs from accepted parent'}
    # Leaf reports in this new job must be freshly produced, never inherited.
    foreach($leaf in @('sim/report/fastv2_layer2_hls_cosim.rpt','sim/report/verilog/result.transaction.rpt')) {
        $path=Join-Path $job "projects/layer2/solution1/$leaf"
        if (Test-Path -LiteralPath $path) {Remove-Item -LiteralPath $path}
    }
    foreach($script in @('prepare_layer2_benchmark.py','oracle.py')) {
        Copy-Item -LiteralPath (Join-Path $Orb60Root "tests/$script") -Destination (Join-Path $job "inputs/$script")
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'report_layer2_benchmark.py') -Destination $job
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'layer2_benchmark.tcl') -Destination $job
    $image=Join-Path $job 'inputs/FPGA_ORB_SHARED_v1.0/vectors/flight_20261004T184929_998838_6bb93c56_f0000/input.pgm'
    & $ProjectPython (Join-Path $job 'inputs/prepare_layer2_benchmark.py') --input $image --output (Join-Path $job 'vectors')
    if ($LASTEXITCODE) {throw 'Independent benchmark preparation failed'}
    $state.Stage='NATIVE_EXACT';$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
    $source=Join-Path $Orb60Root 'optimized/FPGA_ORB_HLS/fastv2/next'
    $hostBuild=Join-Path $Orb60Root 'build/optimized/host'
    & $Orb60CMake -S $source -B $hostBuild -G Ninja "-DCMAKE_MAKE_PROGRAM=$Orb60Ninja" "-DCMAKE_CXX_COMPILER=$Orb60Cxx" "-DCMAKE_C_COMPILER=$Orb60C" -DCMAKE_BUILD_TYPE=Release
    if ($LASTEXITCODE) {throw 'Benchmark host configure failed'}
    & $Orb60CMake --build $hostBuild --target next_layer2_benchmark --parallel 4
    if ($LASTEXITCODE) {throw 'Benchmark host compile failed'}
    & (Join-Path $hostBuild 'next_layer2_benchmark.exe') (Join-Path $job 'vectors') | Tee-Object -FilePath (Join-Path $job 'native.log')
    if ($LASTEXITCODE) {throw 'Native exact benchmark failed'}
    $state.Stage='RTL_COSIM';$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
    $env:ORB60_BENCH_JOB=$job.Replace('\','/')
    $env:ORB60_BENCH_PARENT=$parent.Replace('\','/')
    Push-Location $job
    try {
        $ErrorActionPreference='Continue'
        & $VitisHlsBat -nolog -f (Join-Path $job 'layer2_benchmark.tcl') 2>&1 | Tee-Object -FilePath (Join-Path $job 'tool.log')
        $code=$LASTEXITCODE
        $ErrorActionPreference='Stop'
    } finally {Pop-Location}
    if ($code -ne 0 -or !(Test-Path -LiteralPath (Join-Path $job 'success.stamp'))) {throw "Benchmark RTL failed (exit $code)"}
    $after=RtlManifest $rtl
    $after | Set-Content -LiteralPath (Join-Path $job 'rtl_manifest_after.json') -Encoding UTF8
    if ($before -ne $after) {throw 'RTL changed during benchmark: invalid comparison'}
    $state.Stage='REPORT';$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
    & $ProjectPython (Join-Path $job 'report_layer2_benchmark.py') --job $job --archive (Join-Path $ProjectRoot 'r11/r11/release/R11_PROFILE_OPTIONAL') --output (Join-Path $job 'performance.json')
    if ($LASTEXITCODE) {throw 'Benchmark timing post-check failed'}
    $state.State='SUCCEEDED';$state.Stage='COMPLETE'
} catch {$state.State='FAILED';$state['Error']=$_.Exception.Message;throw}
finally {$state['FinishedUtc']=[DateTime]::UtcNow.ToString('o');$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8}
