param(
    [string]$RuntimeIn = "requirements.txt",
    [string]$RuntimeOut = "requirements.lock.txt",
    [string]$DevIn = "requirements-dev.txt",
    [string]$DevOut = "requirements-dev.lock.txt"
)

function Convert-ToPinned {
    param([string]$Path)

    $out = @()
    foreach ($line in Get-Content $Path) {
        $trim = $line.Trim()
        if (-not $trim -or $trim.StartsWith("#")) {
            if ($trim) { $out += $trim }
            continue
        }

        if ($trim -match "^([A-Za-z0-9_.-]+)\s*(==|>=)\s*([A-Za-z0-9_.-]+)$") {
            $name = $Matches[1]
            $ver = $Matches[3]
            $out += "$name==$ver"
        } else {
            throw "Unsupported requirement format in ${Path}: '$trim'"
        }
    }
    return $out
}

$runtimePinned = Convert-ToPinned -Path $RuntimeIn
$devPinned = Convert-ToPinned -Path $DevIn

@(
    "# Auto-generated from $RuntimeIn",
    "# Regenerate: .\\scripts\\update_lockfiles.ps1"
) + $runtimePinned | Set-Content $RuntimeOut -Encoding utf8

@(
    "# Auto-generated from $DevIn",
    "# Regenerate: .\\scripts\\update_lockfiles.ps1"
) + $devPinned | Set-Content $DevOut -Encoding utf8

Write-Host "Updated $RuntimeOut and $DevOut"
