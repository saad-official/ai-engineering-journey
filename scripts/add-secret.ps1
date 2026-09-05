<#
.SYNOPSIS
  Store an API key in the workspace .env (and optionally as a Windows user env var)
  without the value appearing in any chat, terminal history, or git.

.EXAMPLE
  .\scripts\add-secret.ps1 -Name GEMINI_API_KEY
  .\scripts\add-secret.ps1 -Name GROQ_API_KEY -AlsoUserEnv
#>
param(
  [Parameter(Mandatory = $true)][string]$Name,
  [switch]$AlsoUserEnv
)

$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"

$secure = Read-Host -Prompt "Paste value for $Name (input hidden)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }

if ([string]::IsNullOrWhiteSpace($value)) { Write-Error "Empty value, nothing written."; exit 1 }

if (-not (Test-Path $envFile)) {
  Copy-Item (Join-Path $root ".env.example") $envFile
}

$lines = Get-Content $envFile
$pattern = "^\s*#?\s*$([regex]::Escape($Name))="
if ($lines | Where-Object { $_ -match $pattern }) {
  $lines = $lines | ForEach-Object { if ($_ -match $pattern) { "$Name=$value" } else { $_ } }
} else {
  $lines += "$Name=$value"
}
Set-Content -Path $envFile -Value $lines -Encoding utf8

if ($AlsoUserEnv) {
  [Environment]::SetEnvironmentVariable($Name, $value, "User")
  Write-Host "$Name written to .env and to your user environment (open a new terminal to see it)."
} else {
  Write-Host "$Name written to .env"
}
$value = $null
