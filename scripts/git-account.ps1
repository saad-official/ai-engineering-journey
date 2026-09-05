<#
.SYNOPSIS
  Switch the active GitHub CLI account between personal and work, and show which git
  identity applies in the current folder.

.DESCRIPTION
  How the two-account setup works on this machine:
   - git identity (name/email) is chosen automatically per folder by includeIf rules in
     ~/.gitconfig: anything under "G:\AI Engineering Journey\" or "G:\personal\" uses
     ~/.gitconfig-personal (saad-official); everything else uses the global (work) identity.
   - Authentication is chosen by which `gh` account is active. Personal repos use HTTPS
     remotes, so git pushes use the active gh account's token via gh's credential helper.
     Work repos keep their SSH remotes, which always use the SSH key regardless of gh.
   - So: switching = `gh auth switch`, and this script is just a memorable wrapper.

.EXAMPLE
  .\scripts\git-account.ps1 personal
  .\scripts\git-account.ps1 work
  .\scripts\git-account.ps1 status
#>
param(
  [Parameter(Position = 0)]
  [ValidateSet("personal", "work", "status")]
  [string]$Target = "status"
)

$accounts = @{ personal = "saad-official"; work = "SadiPro07" }

if ($Target -ne "status") {
  $user = $accounts[$Target]
  gh auth switch --hostname github.com --user $user
  if (-not $?) {
    Write-Host "Account '$user' is not logged in yet. Run:  gh auth login -h github.com -p https -w" -ForegroundColor Yellow
    Write-Host "then re-run this script." -ForegroundColor Yellow
    exit 1
  }
}

Write-Host "`ngh active account:" -ForegroundColor Cyan
gh auth status 2>&1 | Select-String -Pattern "Logged in|Active account" | ForEach-Object { "  " + $_.Line.Trim() }

Write-Host "`ngit identity in this folder ($(Get-Location)):" -ForegroundColor Cyan
$inRepo = git rev-parse --is-inside-work-tree 2>$null
if ($inRepo -eq "true") {
  "  {0} <{1}>" -f (git config user.name), (git config user.email)
  $remote = git remote get-url origin 2>$null
  if ($remote) { "  origin: $remote" }
} else {
  "  (not inside a git repo; global identity: $(git config --global user.name))"
}
