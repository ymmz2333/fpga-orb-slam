param(
    [Parameter(Mandatory=$true)][string]$BundleRoot,
    [Parameter(Mandatory=$true)][string]$Output,
    [ValidateSet('Top','HlsLayer','HlsDescriptor')][string]$Stage='Top',
    [ValidateRange(1,16)][int]$Jobs=4,
    [switch]$ValidateOnly
)
$ErrorActionPreference='Stop'
$BundleRoot=(Resolve-Path -LiteralPath $BundleRoot).Path
. (Join-Path $BundleRoot 'scripts\project_env.ps1')
$Output=[IO.Path]::GetFullPath($Output)
if(Test-Path -LiteralPath $Output){throw 'Output must be a new directory'}
if($Output.Contains(' ')){throw 'Use a short output path without spaces for AMD IP tools'}
$saved=@{}
$names=@('ORB60_HLS_JOB','ORB60_HLS_KERNEL','ORB60_HLS_PERIOD','ORB60_HLS_CSIM_ONLY','ORB60_HLS_COSIM','ORB60_HLS_NO_EXPORT',
 'ORB60_DESCRIPTOR_WIDTH_MODE','ORB60_DESCRIPTOR_PREFETCH','ORB60_DESCRIPTOR_PATCH32','ORB60_DESCRIPTOR_MOMENT_FUSION',
 'ORB60_DESCRIPTOR_FAST_QUANTIZE','ORB60_SLICE_COMPACT_MODE','ORB60_LAYER_PPC','ORB60_FAST_STAGED','ORB60_LAYER_IO_OVERLAP',
 'ORB60_LAYER_BRAM_FIFOS','ORB60_ORB_TIMING_ROOT','ORB60_ORB_TIMING_JOBS','ORB60_ORB_TIMING_FREQUENCY',
 'ORB60_ORB_TIMING_PPC','ORB60_CONTROL_SLICE_MODE','ORB60_FREQUENCY_VALIDATE_ONLY','ORB60_BUNDLE_BIT_JOB')
foreach($name in $names){$saved[$name]=[Environment]::GetEnvironmentVariable($name,'Process');[Environment]::SetEnvironmentVariable($name,$null,'Process')}
try{
    $null=New-Item -ItemType Directory -Path $Output
    if($Stage -eq 'Top'){
        if(-not $VivadoBat){throw 'Set FPGA_VIVADO_ROOT to the 2024.2 installation'}
        Copy-Item -LiteralPath (Join-Path $BundleRoot 'fpga_baseline\top_inputs') -Destination (Join-Path $Output 'inputs') -Recurse
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $null=New-Item -ItemType Directory -Path (Join-Path $Output 'ip')
        foreach($item in @(@('layer','layer2'),@('desc','descriptor'))){
            $archive=Join-Path $BundleRoot ('fpga_baseline\ip\xilinx_com_hls_fastv2_'+$item[1]+'_hls_1_0.zip')
            [IO.Compression.ZipFile]::ExtractToDirectory($archive,(Join-Path $Output ('ip\'+$item[0])))
        }
        $env:ORB60_ORB_TIMING_ROOT=$Output;$env:ORB60_ORB_TIMING_JOBS="$Jobs"
        $env:ORB60_ORB_TIMING_FREQUENCY='150';$env:ORB60_ORB_TIMING_PPC='4';$env:ORB60_CONTROL_SLICE_MODE='7'
        $env:ORB60_FREQUENCY_VALIDATE_ONLY=[string][int]$ValidateOnly.IsPresent
        & $VivadoBat -mode batch -source (Join-Path $Output 'inputs\build_orb_frequency.tcl') -log (Join-Path $Output 'vivado.log') -journal (Join-Path $Output 'vivado.jou') *> (Join-Path $Output 'vivado.console.log')
        if($LASTEXITCODE -ne 0){throw 'Vivado top build failed'}
        if(-not $ValidateOnly){
            if(-not(Test-Path -LiteralPath (Join-Path $Output 'vivado\.vivado_timing_success'))){throw 'Missing strict route acceptance stamp'}
            $env:ORB60_BUNDLE_BIT_JOB=$Output
            & $VivadoBat -mode batch -source (Join-Path $BundleRoot 'tools\write_bitstream.tcl') -log (Join-Path $Output 'bit.log') -journal (Join-Path $Output 'bit.jou') *> (Join-Path $Output 'bit.console.log')
            if($LASTEXITCODE -ne 0){throw 'Bitstream export failed'}
        }
    }else{
        if(-not $VitisHlsBat){throw 'Set FPGA_VITIS_HLS_ROOT to the 2024.2 installation'}
        $kernel=if($Stage -eq 'HlsLayer'){'layer2'}else{'descriptor'}
        $snapshot=Join-Path $BundleRoot ('fpga_baseline\'+$kernel)
        Copy-Item -LiteralPath (Join-Path $snapshot 'inputs') -Destination (Join-Path $Output 'inputs') -Recurse
        if($kernel -eq 'descriptor'){Copy-Item -LiteralPath (Join-Path $snapshot 'descriptor_vectors') -Destination (Join-Path $Output 'descriptor_vectors') -Recurse}
        $env:ORB60_HLS_JOB=$Output;$env:ORB60_HLS_KERNEL=$kernel;$env:ORB60_HLS_PERIOD='6.666666666666667'
        $env:ORB60_HLS_CSIM_ONLY='0';$env:ORB60_HLS_COSIM='1';$env:ORB60_HLS_NO_EXPORT='0'
        if($kernel -eq 'layer2'){
            $env:ORB60_SLICE_COMPACT_MODE='2';$env:ORB60_LAYER_PPC='4';$env:ORB60_FAST_STAGED='1'
            $env:ORB60_LAYER_IO_OVERLAP='1';$env:ORB60_LAYER_BRAM_FIFOS='1'
        }else{
            $env:ORB60_DESCRIPTOR_WIDTH_MODE='2';$env:ORB60_DESCRIPTOR_PREFETCH='8';$env:ORB60_DESCRIPTOR_PATCH32='1'
            $env:ORB60_DESCRIPTOR_MOMENT_FUSION='1';$env:ORB60_DESCRIPTOR_FAST_QUANTIZE='1'
        }
        & $VitisHlsBat -f (Join-Path $snapshot 'hls.tcl') *> (Join-Path $Output 'hls.log')
        if($LASTEXITCODE -ne 0 -or -not(Test-Path -LiteralPath (Join-Path $Output 'success.stamp'))){throw 'HLS rebuild failed'}
    }
    Write-Output "HANDOFF_BUILD_COMPLETE stage=$Stage output=$Output validate_only=$ValidateOnly"
}finally{foreach($name in $names){[Environment]::SetEnvironmentVariable($name,$saved[$name],'Process')}}
