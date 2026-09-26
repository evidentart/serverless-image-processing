$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$buildRoot = Join-Path $projectRoot ".phase4-build\processor-package"
$processorPackage = Join-Path $buildRoot "processor"
$requirements = Join-Path $projectRoot "lambda\requirements-processing.txt"

if (Test-Path -LiteralPath $buildRoot) {
    Remove-Item -LiteralPath $buildRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $processorPackage -Force | Out-Null

python -m pip install `
    --requirement $requirements `
    --target $buildRoot `
    --platform manylinux_2_28_x86_64 `
    --python-version 3.12 `
    --implementation cp `
    --abi cp312 `
    --only-binary=:all: `
    --no-deps `
    --no-compile `
    --upgrade

Copy-Item (Join-Path $projectRoot "lambda\processor_handler.py") $buildRoot
Copy-Item (Join-Path $projectRoot "processor\process_image.py") $processorPackage
Copy-Item (Join-Path $projectRoot "processor\__init__.py") $processorPackage

Write-Output "Created Lambda package at $buildRoot"
