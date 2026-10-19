# Launcher: keeps every library cache inside the project (CLAUDE.md guardrail), then runs the CLI.
#   .\run.ps1 run [--offline]          full pipeline
#   .\run.ps1 stage presentation --from runs\<id>
#   .\run.ps1 eval [--live]            eval suite
#   .\run.ps1 render-pages runs\<id>
#   .\run.ps1 test [pytest args]       unit tests
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:MPLCONFIGDIR = Join-Path $root ".cache\matplotlib"
$env:PYTHONPYCACHEPREFIX = Join-Path $root ".cache\pycache"
$py = Join-Path $root ".venv\Scripts\python.exe"
Push-Location $root
try {
    if ($args.Count -gt 0 -and $args[0] -eq "test") {
        & $py -m pytest @($args | Select-Object -Skip 1)
    } else {
        & $py -m strategy @args
    }
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $code
