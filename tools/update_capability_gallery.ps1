[CmdletBinding()]
param(
    [string]$PythonExe = "",
    [switch]$IncludeValidationReports,
    [switch]$SkipGalleryCheck,
    [switch]$SkipSphinxBuild,
    [switch]$OpenHtml
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$docsRoot = Join-Path $repoRoot "docs\readthedocs"
$htmlIndex = Join-Path $docsRoot "_build\html\capability_gallery\index.html"

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $PythonExe = (Get-Command python -ErrorAction Stop).Source
}

function Invoke-PythonStep {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    Write-Host ""
    Write-Host "==> $Title" -ForegroundColor Cyan
    Write-Host "    cwd: $WorkingDirectory"
    Write-Host "    cmd: $PythonExe $($Arguments -join ' ')"

    Push-Location $WorkingDirectory
    try {
        & $PythonExe @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw ("Step failed with exit code {0}: {1}" -f $LASTEXITCODE, $Title)
        }
    }
    finally {
        Pop-Location
    }
}

Write-Host "Repository root: $repoRoot"
Write-Host "Python: $PythonExe"

if ($IncludeValidationReports) {
    Invoke-PythonStep `
        -Title "Refresh validation batch reports" `
        -WorkingDirectory $repoRoot `
        -Arguments @("-m", "validation_cases.update_reports", "--no-show")
}
else {
    Write-Host ""
    Write-Host "==> Skipping validation batch reports (use -IncludeValidationReports to refresh them)." -ForegroundColor Yellow
}

Invoke-PythonStep `
    -Title "Refresh capability gallery sources and static artifacts" `
    -WorkingDirectory $repoRoot `
    -Arguments @("-m", "tools.doc_gallery")

if (-not $SkipGalleryCheck) {
    Invoke-PythonStep `
        -Title "Check generated capability gallery artifacts" `
        -WorkingDirectory $repoRoot `
        -Arguments @("-m", "tools.doc_gallery", "--check")
}

if (-not $SkipSphinxBuild) {
    Invoke-PythonStep `
        -Title "Build Sphinx HTML" `
        -WorkingDirectory $docsRoot `
        -Arguments @("-m", "sphinx", "-E", "-a", "-W", "-b", "html", "source", "_build/html")
}

Write-Host ""
Write-Host "Capability gallery refresh completed." -ForegroundColor Green
Write-Host "HTML index: $htmlIndex"

if ($OpenHtml) {
    if (-not (Test-Path -LiteralPath $htmlIndex)) {
        throw "HTML index not found: $htmlIndex"
    }
    Start-Process $htmlIndex
}
