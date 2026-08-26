# populate.ps1 -- fill beardog-content from the last v1 release output.
#
# Run this ONCE, from inside the beardog-content folder, after cloning it.
# It reads from the launcher repo's out\ directory and writes addons\ and
# client\ here. It does not commit or push anything.
#
# Pure ASCII on purpose: Windows PowerShell 5.1 chokes on smart punctuation.

[CmdletBinding()]
param(
  [string]$Source = "D:\Downloads\bear-dog-launcher",
  [string]$Dest   = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'

# The seven groups that ship from this repo. Everything else either comes from
# the author's own GitHub repo or from the player's client. See README.md.
$bundled = @(
  'classicapi',
  'superapi',
  'unitxp-sp3',
  'nampower-settings',
  'wowtranslate',
  'cnfix-names',
  'msbt'
)

$zipDir    = Join-Path $Source 'out\addons'
$clientDir = Join-Path $Source 'out\client\1.12.1\files'

if (-not (Test-Path -LiteralPath $zipDir))    { throw "No addon zips at $zipDir" }
if (-not (Test-Path -LiteralPath $clientDir)) { throw "No client files at $clientDir" }

$addonsOut = Join-Path $Dest 'addons'
$clientOut = Join-Path $Dest 'client'
New-Item -ItemType Directory -Force -Path $addonsOut | Out-Null
New-Item -ItemType Directory -Force -Path $clientOut | Out-Null

Write-Host ''
Write-Host 'Addons:' -ForegroundColor Cyan
foreach ($id in $bundled) {
  $zip = Join-Path $zipDir "$id.zip"
  if (-not (Test-Path -LiteralPath $zip)) { throw "Missing $zip" }
  Expand-Archive -LiteralPath $zip -DestinationPath $addonsOut -Force
  Write-Host ("  {0}" -f $id)
}

Write-Host ''
Write-Host 'Client files:' -ForegroundColor Cyan
# Copy the CONTENTS of files\ into client\, not the files\ folder itself --
# Copy-Item on a directory nests it inside an existing destination.
Get-ChildItem -LiteralPath $clientDir | ForEach-Object {
  Copy-Item -LiteralPath $_.FullName -Destination $clientOut -Recurse -Force
}
Get-ChildItem -LiteralPath $clientOut -Recurse -File |
  ForEach-Object { Write-Host ("  {0}" -f $_.FullName.Substring($clientOut.Length + 1)) }

# The one file whose size we know exactly, and the one that has bitten before.
$patch = Join-Path $clientOut 'Data\patch-Q.MPQ'
if (-not (Test-Path -LiteralPath $patch)) { throw "patch-Q.MPQ did not land at $patch" }
$size = (Get-Item -LiteralPath $patch).Length
if ($size -ne 12822) { throw "patch-Q.MPQ is $size bytes, expected 12822" }

$stale = Get-ChildItem -LiteralPath (Join-Path $clientOut 'Data') -Filter 'patch-Y*' -ErrorAction SilentlyContinue
if ($stale) { throw "A stale patch-Y file is present: $($stale.Name)" }

$folders = (Get-ChildItem -LiteralPath $addonsOut -Directory).Count
$files   = (Get-ChildItem -LiteralPath $clientOut -Recurse -File).Count

Write-Host ''
Write-Host ("Done. {0} addon folders, {1} client files." -f $folders, $files) -ForegroundColor Green
Write-Host 'Expected: 8 addon folders, 21 client files.'
Write-Host ''
Write-Host 'Nothing has been committed. Review with "git status", then commit and push.'
