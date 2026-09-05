<#
.SYNOPSIS
  Wait for the Ollama installer download to finish, verify it, install to G:\Ollama silently,
  then pull the Phase 0 model set. Safe to re-run; skips steps already done.

  Expects user env vars already set: OLLAMA_MODELS=G:\ollama-models, CUDA_VISIBLE_DEVICES=-1,
  OLLAMA_VULKAN=0 (see TECHNOLOGY_STACK.md section 3).
#>
$ErrorActionPreference = "Stop"
$installer = "G:\_tooltmp\ollama\OllamaSetup.exe"
$installDir = "G:\Ollama"
$models = @("qwen3:1.7b", "nomic-embed-text", "qwen3-embedding:0.6b", "qwen3.5:4b")  # smallest first

function Log($m) { "{0}  {1}" -f (Get-Date -Format "HH:mm:ss"), $m }

# 1. Wait for the download to complete (size must match Content-Length and stop changing).
$expected = [int64](Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -Method Head -UseBasicParsing).Headers['Content-Length']
Log "Installer expected size: $([math]::Round($expected/1MB)) MB"
$stable = 0
while ($true) {
  if (-not (Test-Path $installer)) { throw "Installer file missing: $installer" }
  $size = (Get-Item $installer).Length
  if ($size -ge $expected) { break }
  $stable = 0
  Start-Sleep -Seconds 60
  $size2 = (Get-Item $installer).Length
  if ($size2 -eq $size) { $stable++ ; if ($stable -ge 10) { throw "Download stalled at $([math]::Round($size/1MB)) MB for 10 minutes. Re-download and re-run." } }
  Log "Downloading... $([math]::Round($size2/1MB)) / $([math]::Round($expected/1MB)) MB"
}
Log "Download complete."

# 2. Verify Authenticode signature before executing anything.
$sig = Get-AuthenticodeSignature $installer
if ($sig.Status -ne "Valid") { throw "Installer signature is $($sig.Status); refusing to run it." }
Log "Signature valid: $($sig.SignerCertificate.Subject)"

# 3. Install silently to G:\Ollama (Inno Setup switches).
if (-not (Test-Path "$installDir\ollama.exe")) {
  Log "Installing to $installDir ..."
  $p = Start-Process -FilePath $installer -ArgumentList "/DIR=`"$installDir`"", "/SILENT", "/NORESTART" -Wait -PassThru
  if ($p.ExitCode -ne 0) { throw "Installer exited with code $($p.ExitCode)" }
  Log "Installed."
} else { Log "Already installed." }

# 4. Make sure the server is running, then pull models.
$env:Path = "$installDir;$env:Path"
$env:OLLAMA_MODELS = "G:\ollama-models"; $env:CUDA_VISIBLE_DEVICES = "-1"; $env:OLLAMA_VULKAN = "0"
$up = $false
for ($i = 0; $i -lt 12 -and -not $up; $i++) {
  try { Invoke-RestMethod "http://localhost:11434/api/version" -TimeoutSec 5 | Out-Null; $up = $true } catch { Start-Sleep 5 }
}
if (-not $up) {
  Log "Server not detected; starting 'ollama serve' in the background."
  Start-Process -FilePath "$installDir\ollama.exe" -ArgumentList "serve" -WindowStyle Hidden
  Start-Sleep 10
}
Log "Ollama version: $((Invoke-RestMethod 'http://localhost:11434/api/version').version)"

foreach ($m in $models) {
  Log "Pulling $m ..."
  & "$installDir\ollama.exe" pull $m
  if (-not $?) { Log "WARNING: pull failed for $m (continuing)" }
}
Log "Installed models:"
& "$installDir\ollama.exe" list
Log "Model store size: $([math]::Round(((Get-ChildItem 'G:\ollama-models' -Recurse -File | Measure-Object Length -Sum).Sum)/1GB, 2)) GB"
Log "Done. Run labs/01-hello-llm again to include the local model."
