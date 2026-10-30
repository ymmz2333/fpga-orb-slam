param([ValidateSet('Reference','Compile')][string]$Stage = 'Reference',
      [ValidateSet('DepthAnything','MidasSmall')][string]$Model = 'DepthAnything',
      [string]$Attempt)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
if (-not $Attempt) { $Attempt = if ($Model -eq 'DepthAnything') { 'da2-small-fp16' } else { 'midas-small-fp16' } }
if ($Attempt -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Unsafe attempt name' }
$build = Join-Path $ProjectRoot 'orb60/build/dense'
$settings = Get-Content -Raw (Join-Path $build 'conversion.local.json') | ConvertFrom-Json
$wslExe = Join-Path $env:SystemRoot 'System32/wsl.exe'
$attemptRoot = Join-Path $build $Attempt
New-Item -Force -ItemType Directory $attemptRoot | Out-Null
$linuxOutput = (& $wslExe -d $settings.distribution --exec wslpath -a $attemptRoot).Trim()
if ($Stage -eq 'Reference') {
    $script = Join-Path $PSScriptRoot $(if ($Model -eq 'DepthAnything') { 'export_depth_anything.py' } else { 'reference_midas.py' })
    $linuxScript = (& $wslExe -d $settings.distribution --exec wslpath -a $script).Trim()
    $sampleName = if ($Model -eq 'DepthAnything') { 'samples' } else { 'samples-midas' }
    $linuxSamples = (& $wslExe -d $settings.distribution --exec wslpath -a (Join-Path $build $sampleName)).Trim()
    & $wslExe -d $settings.distribution --exec $settings.python $linuxScript --assets $settings.assets --samples $linuxSamples --output $linuxOutput
} else {
    $script = Join-Path $PSScriptRoot 'convert_rknn.py'
    $linuxScript = (& $wslExe -d $settings.distribution --exec wslpath -a $script).Trim()
    $onnxName = if ($Model -eq 'DepthAnything') { 'depth_anything_v2_small_518x392.onnx' } else { 'midas_small_256.onnx' }
    & $wslExe -d $settings.distribution --exec $settings.python $linuxScript --onnx "$linuxOutput/$onnxName" --output "$linuxOutput/depth.rknn"
}
if ($LASTEXITCODE -ne 0) { throw "Dense $Stage failed; preserve this attempt's logs" }
