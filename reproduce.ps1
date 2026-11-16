param([int]$Size = 1000, [string]$Output = 'runs/proof', [switch]$NativeOnly)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $arguments = @('-3.12', '-X', 'utf8', '-B', 'scripts/reproduce.py', '--n', "$Size", '--out', $Output)
    if ($NativeOnly) { $arguments += '--native-only' }
    & py @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Reproduction failed; inspect the output directory logs.' }
} finally { Pop-Location }
