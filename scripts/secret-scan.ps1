param(
    [switch]$AllFiles = $false
)

$ErrorActionPreference = "Stop"

$excludeFragments = @(
    "\.git\",
    "\.venv\",
    "\venv_linux\",
    "\node_modules\",
    "\backend\data\cache\",
    "\backend\data\live\",
    "\backend\backend\data\"
)

$secretPatterns = @(
    "-----BEGIN (RSA |OPENSSH |EC |DSA |)PRIVATE KEY-----",
    "AKIA[0-9A-Z]{16}",
    "(BINANCE|TESTNET)?_?API_(KEY|SECRET)\s*=\s*[""'][A-Za-z0-9_\-]{20,}[""']",
    "(API_KEY|API_SECRET|TOKEN|PASSWORD|SECRET_KEY)\s*=\s*[""'][^""']{20,}[""']",
    "^VITE_.*(SECRET|TOKEN|KEY)=.+$"
)

$placeholderPattern = "(your_|example|placeholder|changeme|change_me|dummy|test_key|test_secret|\$\{\{\s*secrets\.)"

if ($AllFiles) {
    $files = rg --files -g "!venv_linux/**" -g "!.venv/**" -g "!frontend/node_modules/**" -g "!backend/data/cache/**" -g "!backend/data/live/**" -g "!backend/backend/data/**"
} else {
    $files = git -c core.quotepath=false ls-files
}

$findings = foreach ($file in $files) {
    try {
        $exists = Test-Path -LiteralPath $file -PathType Leaf
    } catch {
        continue
    }
    if (-not $exists) {
        continue
    }

    $fullPath = (Resolve-Path -LiteralPath $file).Path
    if ($excludeFragments | Where-Object { $fullPath -like "*$_*" }) {
        continue
    }

    $lineNo = 0
    try {
        Get-Content -LiteralPath $file -ErrorAction Stop | ForEach-Object {
            $lineNo++
            $line = $_
            if ($line -match $placeholderPattern) {
                return
            }
            if ($line -match "startswith\(" -or $line -match "split\(" -or $line -match "os\.getenv\(") {
                return
            }
            foreach ($pattern in $secretPatterns) {
                if ($line -match $pattern) {
                    [pscustomobject]@{
                        Path = $file
                        Line = $lineNo
                        Kind = if ($Matches[1]) { $Matches[1] } else { "secret" }
                    }
                    break
                }
            }
        }
    } catch {
        continue
    }
}

if ($findings) {
    $findings | Sort-Object Path, Line | Format-Table -AutoSize
    Write-Error "Potential committed secrets found. Values were intentionally not printed."
}

Write-Host "Secret scan passed."
