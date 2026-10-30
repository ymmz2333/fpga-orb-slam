$ErrorActionPreference = 'Stop'
$Orb60Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $Orb60Root '..'))
. (Join-Path $ProjectRoot 'scripts/project_env.ps1')
$Orb60CMake = (Get-Command cmake.exe -ErrorAction Stop).Source
$Orb60Ninja = (Get-Command ninja.exe -ErrorAction Stop).Source
$Orb60Cxx = (Get-Command g++.exe -ErrorAction Stop).Source
$Orb60C = (Get-Command gcc.exe -ErrorAction Stop).Source
$Orb60CTest = Join-Path (Split-Path -Parent $Orb60CMake) 'ctest.exe'
# Host executables must load the same MinGW runtime that compiled them. AMD's
# tools also ship libstdc++ DLLs; their PATH precedence breaks native host tools.
$env:PATH = (Split-Path -Parent $Orb60Cxx) + ';' + $env:PATH
