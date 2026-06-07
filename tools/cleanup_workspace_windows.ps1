param(
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Patterns = @(
    ".codex_*",
    ".codex_pytest_tmp*",
    ".mypy_cache",
    ".pytest*",
    ".ruff_cache",
    ".tmp*",
    "codex_validation_*",
    "hydromodpy.egg-info",
    "mesh-sim-int-*",
    "pytest-cache-files-*",
    "pytest-temp-root",
    "pytestscratch*",
    "river_trace_smoke_*",
    "scratch_*",
    "test_tmp*",
    "timing_reports",
    "tmp",
    "tmp*"
)

function Test-MatchesCleanupPattern {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )
    foreach ($pattern in $Patterns) {
        if ($Name -like $pattern) {
            return $true
        }
    }
    return $false
}

function Test-IsGitIgnored {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RelativePath
    )
    & git check-ignore -q -- $RelativePath
    return $LASTEXITCODE -eq 0
}

function Test-HasTrackedContent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RelativePath
    )
    $tracked = & git ls-files -- $RelativePath
    return -not [string]::IsNullOrWhiteSpace(($tracked -join "`n"))
}

function Get-RepoRelativePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FullPath
    )
    if (-not $FullPath.StartsWith($RepoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside repo root: $FullPath"
    }
    return $FullPath.Substring($RepoRoot.Length).TrimStart('\').Replace('\', '/')
}

function Get-CleanupCandidates {
    $items = Get-ChildItem -LiteralPath $RepoRoot -Force -Directory |
        Sort-Object Name
    $candidates = @()
    foreach ($item in $items) {
        if (-not (Test-MatchesCleanupPattern -Name $item.Name)) {
            continue
        }
        $relativePath = Get-RepoRelativePath -FullPath $item.FullName
        if (-not (Test-IsGitIgnored -RelativePath $relativePath)) {
            continue
        }
        if (Test-HasTrackedContent -RelativePath $relativePath) {
            continue
        }
        $candidates += $item
    }
    return $candidates
}

function Remove-CandidateDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [System.IO.DirectoryInfo]$Directory
    )
    $target = $Directory.FullName
    if (-not $target.StartsWith($RepoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to delete path outside repo root: $target"
    }

    try {
        & attrib -R -S -H $target 2>$null | Out-Null
        & attrib -R -S -H (Join-Path $target "*") /S /D 2>$null | Out-Null
    } catch {
    }

    try {
        & takeown /F $target /R /D O 2>$null | Out-Null
    } catch {
    }

    try {
        & icacls $target /grant "$env:USERNAME`:(OI)(CI)F" /T /C 2>$null | Out-Null
    } catch {
    }

    Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction Stop
}

$candidates = Get-CleanupCandidates
if ($candidates.Count -eq 0) {
    Write-Output "No ignored root-level temporary directories found."
    exit 0
}

$prefix = if ($Apply) { "DELETE" } else { "DRY-RUN" }
foreach ($candidate in $candidates) {
    $relativePath = Get-RepoRelativePath -FullPath $candidate.FullName
    Write-Output "$prefix $relativePath"
}

if (-not $Apply) {
    Write-Output "$($candidates.Count) candidate(s). Re-run with -Apply to delete them."
    exit 0
}

$failures = @()
foreach ($candidate in $candidates) {
    try {
        Remove-CandidateDirectory -Directory $candidate
    } catch {
        $relativePath = Get-RepoRelativePath -FullPath $candidate.FullName
        $failures += [pscustomobject]@{
            Path = $relativePath
            Error = $_.Exception.Message
        }
    }
}

if ($failures.Count -gt 0) {
    foreach ($failure in $failures) {
        Write-Error "FAILED $($failure.Path): $($failure.Error)"
    }
    exit 1
}

Write-Output "Deleted $($candidates.Count) directory(ies)."
