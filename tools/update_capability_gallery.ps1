[CmdletBinding()]
param(
    [string]$PythonExe = "",
    [string]$CondaEnv = "",
    [switch]$IncludeValidationReports,
    [switch]$IncludeXt3dDiagnostics,
    [ValidateSet("modflownwt", "modflow6", "modflow6_irregular_tri", "boussinesq")]
    [string[]]$ValidationSolvers = @(),
    [ValidateSet("steady", "transient", "both")]
    [string]$ValidationRegime = "both",
    [string[]]$Only = @(),
    [string[]]$Category = @(),
    [string]$BuildDir = "build/html",
    [switch]$SkipGalleryCheck,
    [switch]$SkipSphinxBuild,
    [switch]$OpenHtml
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-CondaEnvExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    try {
        $raw = & conda env list --json 2>$null
        if ($LASTEXITCODE -ne 0) {
            return $false
        }
        $payload = $raw | ConvertFrom-Json
        foreach ($envPath in @($payload.envs)) {
            if ((Split-Path -Leaf $envPath) -eq $Name) {
                return $true
            }
        }
    }
    catch {
        return $false
    }

    return $false
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$docsRoot = Join-Path $repoRoot "docs\readthedocs"
if ([System.IO.Path]::IsPathRooted($BuildDir)) {
    $resolvedBuildDir = $BuildDir
}
else {
    $resolvedBuildDir = Join-Path $docsRoot $BuildDir
}

$htmlTarget = if ($Only.Count -eq 1 -and $Category.Count -eq 0) {
    Join-Path $resolvedBuildDir ("capability_gallery\cases\" + $Only[0] + ".html")
}
else {
    Join-Path $resolvedBuildDir "capability_gallery\index.html"
}

$needsXt3dDiagnostics = $IncludeXt3dDiagnostics -or $Only.Contains("modflow6_irregular_tri_xt3d_method_choice")
$needsScientificPython = $IncludeValidationReports -or $needsXt3dDiagnostics
if (
    [string]::IsNullOrWhiteSpace($PythonExe) -and
    [string]::IsNullOrWhiteSpace($CondaEnv) -and
    $needsScientificPython -and
    (Test-CondaEnvExists -Name "hydromodpy-kpg")
) {
    $CondaEnv = "hydromodpy-kpg"
}

if ([string]::IsNullOrWhiteSpace($CondaEnv)) {
    if ([string]::IsNullOrWhiteSpace($PythonExe)) {
        $PythonExe = (Get-Command python -ErrorAction Stop).Source
    }
    $script:PythonCommand = @($PythonExe)
}
else {
    $script:PythonCommand = @("conda", "run", "--no-capture-output", "-n", $CondaEnv, "python")
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
    Write-Host "    cmd: $(($script:PythonCommand + $Arguments) -join ' ')"

    Push-Location $WorkingDirectory
    try {
        $launcher = $script:PythonCommand[0]
        $launcherArgs = if ($script:PythonCommand.Count -gt 1) {
            $script:PythonCommand[1..($script:PythonCommand.Count - 1)]
        }
        else {
            @()
        }
        & $launcher @launcherArgs @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw ("Step failed with exit code {0}: {1}" -f $LASTEXITCODE, $Title)
        }
    }
    finally {
        Pop-Location
    }
}

Write-Host "Repository root: $repoRoot"
Write-Host "Python command: $($script:PythonCommand -join ' ')"
Write-Host "Docs HTML build dir: $resolvedBuildDir"

if ($IncludeValidationReports) {
    $validationArgs = @(
        "-m", "validation_cases.update_reports",
        "--no-show",
        "--regime", $ValidationRegime
    )
    if ($ValidationSolvers.Count -gt 0) {
        $validationArgs += "--solvers"
        $validationArgs += $ValidationSolvers
    }
    Invoke-PythonStep `
        -Title "Refresh validation batch reports" `
        -WorkingDirectory $repoRoot `
        -Arguments $validationArgs
}
else {
    Write-Host ""
    Write-Host "==> Skipping validation batch reports (use -IncludeValidationReports to refresh them)." -ForegroundColor Yellow
}

if ($needsXt3dDiagnostics) {
    Invoke-PythonStep `
        -Title "Refresh XT3D irregular-triangle diagnostics report" `
        -WorkingDirectory $repoRoot `
        -Arguments @("-m", "tools.doc_gallery.xt3d_irregular_tri_diagnostics")
}
else {
    Write-Host ""
    Write-Host "==> Skipping XT3D irregular-triangle diagnostics (use -IncludeXt3dDiagnostics or target the XT3D slug)." -ForegroundColor Yellow
}

$galleryArgs = @("-m", "tools.doc_gallery")
foreach ($slug in $Only) {
    $galleryArgs += @("--only", $slug)
}
foreach ($galleryCategory in $Category) {
    $galleryArgs += @("--category", $galleryCategory)
}

Invoke-PythonStep `
    -Title "Refresh capability gallery sources and static artifacts" `
    -WorkingDirectory $repoRoot `
    -Arguments $galleryArgs

if (-not $SkipGalleryCheck) {
    $galleryCheckArgs = @("-m", "tools.doc_gallery", "--check")
    foreach ($slug in $Only) {
        $galleryCheckArgs += @("--only", $slug)
    }
    foreach ($galleryCategory in $Category) {
        $galleryCheckArgs += @("--category", $galleryCategory)
    }
    Invoke-PythonStep `
        -Title "Check generated capability gallery artifacts" `
        -WorkingDirectory $repoRoot `
        -Arguments $galleryCheckArgs
}

if (-not $SkipSphinxBuild) {
    Invoke-PythonStep `
        -Title "Build Sphinx HTML" `
        -WorkingDirectory $docsRoot `
        -Arguments @("-m", "sphinx", "-E", "-a", "-W", "-b", "html", "source", $BuildDir)
}

Write-Host ""
Write-Host "Capability gallery refresh completed." -ForegroundColor Green
Write-Host "HTML target: $htmlTarget"

if ($OpenHtml) {
    if (-not (Test-Path -LiteralPath $htmlTarget)) {
        throw "HTML target not found: $htmlTarget"
    }
    Start-Process $htmlTarget
}
