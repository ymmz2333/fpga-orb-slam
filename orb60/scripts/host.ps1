[CmdletBinding()]
param([ValidateSet('baseline','optimized')][string]$Variant='baseline')
. (Join-Path $PSScriptRoot 'environment.ps1')
$source = Join-Path $Orb60Root "$Variant/FPGA_ORB_HLS/fastv2/next"
$build = Join-Path $Orb60Root "build/$Variant/host"
New-Item -ItemType Directory -Force -Path $build | Out-Null
if($Variant -eq 'optimized') {
    & $ProjectPython (Join-Path $source '../scripts/generate_profile_rom.py')
    if($LASTEXITCODE) {throw 'Profile/segment ROM generation failed'}
    & $ProjectPython (Join-Path $PSScriptRoot 'generate_descriptor_rom.py') --source (Join-Path $source 'include/backend_tables.h') --output (Join-Path $source 'include/descriptor_rom.hpp')
    if($LASTEXITCODE) {throw 'Descriptor ROM generation failed'}
}
& $Orb60CMake -S $source -B $build -G Ninja "-DCMAKE_MAKE_PROGRAM=$Orb60Ninja" "-DCMAKE_CXX_COMPILER=$Orb60Cxx" "-DCMAKE_C_COMPILER=$Orb60C" -DCMAKE_BUILD_TYPE=Release
if ($LASTEXITCODE) { throw 'Host configure failed' }
& $Orb60CMake --build $build --parallel 4
if ($LASTEXITCODE) { throw 'Host build failed' }
& $Orb60CTest --test-dir $build --output-on-failure --timeout 120
if ($LASTEXITCODE) { throw 'Host regression failed' }
