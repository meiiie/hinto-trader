param(
    [string]$OutputPath = "",
    [switch]$Force,
    [switch]$InitGit,
    [switch]$IncludeUntracked
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path (Split-Path $ProjectRoot -Parent) "Hinto_Stock_public"
}

$DestinationParent = Split-Path $OutputPath -Parent
if (-not (Test-Path -LiteralPath $DestinationParent)) {
    New-Item -ItemType Directory -Path $DestinationParent | Out-Null
}

$Destination = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
if ($Destination.Equals($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    $Destination.StartsWith($ProjectRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputPath must be outside the private repository."
}

if (Test-Path -LiteralPath $Destination) {
    if (-not $Force) {
        throw "OutputPath already exists. Pass -Force to replace it: $Destination"
    }
    Remove-Item -LiteralPath $Destination -Recurse -Force
}

New-Item -ItemType Directory -Path $Destination | Out-Null

$denyPrefixes = @(
    ".git/",
    ".agent/",
    ".claude/",
    ".Codex/",
    ".hypothesis/",
    ".kiro/",
    ".venv/",
    ".vscode/",
    "aws/",
    "documents/",
    "plans/",
    "src/",
    "taho-analytics/",
    "venv_linux/",
    "node_modules/",
    "frontend/node_modules/",
    "frontend/dist/",
    "frontend/.vite/",
    "frontend/src-tauri/target/",
    "frontend/src-tauri/gen/",
    "scripts/archive/",
    "backend/scripts/archive/",
    "backend/logs/",
    "backend/backend/data/",
    "backend/data/live/",
    "backend/data/cache/",
    "data/cache/"
)

$denyNames = @(
    "AGENTS.md",
    ".env",
    ".env.local",
    ".env.production",
    ".env.development.local",
    ".env.test.local"
)

$denyExtensions = @(
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".pem",
    ".xlsx",
    ".exe",
    ".dll",
    ".apk"
)

function Should-CopyFile {
    param([string]$RelativePath)

    $normalized = $RelativePath.Replace("\", "/")
    foreach ($prefix in $denyPrefixes) {
        if ($normalized.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $false
        }
    }

    $name = Split-Path $normalized -Leaf
    if ($denyNames -contains $name) {
        return $false
    }

    if ($name -like "*.env" -and $name -ne ".env.example") {
        return $false
    }

    $extension = [System.IO.Path]::GetExtension($name)
    if ($denyExtensions -contains $extension.ToLowerInvariant()) {
        return $false
    }

    return $true
}

Push-Location $ProjectRoot
try {
    $paths = if ($IncludeUntracked) {
        git -c core.quotepath=false ls-files --cached --modified --others --exclude-standard
    } else {
        git -c core.quotepath=false ls-files --cached --modified
    }
    $copied = 0
    foreach ($relativePath in $paths) {
        if ([string]::IsNullOrWhiteSpace($relativePath)) {
            continue
        }
        if (-not (Should-CopyFile -RelativePath $relativePath)) {
            continue
        }

        $source = Join-Path $ProjectRoot $relativePath
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            continue
        }

        $target = Join-Path $Destination $relativePath
        $targetDir = Split-Path $target -Parent
        if (-not (Test-Path -LiteralPath $targetDir)) {
            New-Item -ItemType Directory -Path $targetDir | Out-Null
        }

        Copy-Item -LiteralPath $source -Destination $target -Force
        $copied++
    }

    if ($InitGit) {
        Push-Location $Destination
        try {
            git init | Out-Null
            git add .
        }
        finally {
            Pop-Location
        }
    }

    Write-Host "Public snapshot created: $Destination" -ForegroundColor Green
    Write-Host "Copied files: $copied" -ForegroundColor Green
    if ($InitGit) {
        Write-Host "Initialized Git repository and staged snapshot." -ForegroundColor Green
    }
}
finally {
    Pop-Location
}
