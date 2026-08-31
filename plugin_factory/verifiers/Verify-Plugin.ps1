param(
  [Parameter(Mandatory = $true)][string]$ReleaseRoot,
  [Parameter(Mandatory = $true)][string]$ExpectedReleaseDigest
)

$ErrorActionPreference = "Stop"
function Fail-Verification { throw "plugin verification failed" }

if ($ExpectedReleaseDigest -notmatch '^sha256:[0-9a-f]{64}$') { Fail-Verification }
$root = (Resolve-Path -LiteralPath $ReleaseRoot).Path
$checksumPath = Join-Path $root "SHA256SUMS"
if (-not (Test-Path -LiteralPath $checksumPath -PathType Leaf)) { Fail-Verification }
if ((Get-Item -LiteralPath $checksumPath).Attributes -band [IO.FileAttributes]::ReparsePoint) { Fail-Verification }
$checksumDigest = (Get-FileHash -LiteralPath $checksumPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ("sha256:$checksumDigest" -cne $ExpectedReleaseDigest) { Fail-Verification }

$allFiles = @(Get-ChildItem -LiteralPath $root -Recurse -Force -File)
$allEntries = @(Get-ChildItem -LiteralPath $root -Recurse -Force)
if ($allEntries | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) { Fail-Verification }

$previous = ""
$listed = 0
foreach ($line in Get-Content -LiteralPath $checksumPath -Encoding ASCII) {
  if ($line -notmatch '^([0-9a-f]{64})  ([A-Za-z0-9._/-]+)$') { Fail-Verification }
  $expected = $Matches[1]
  $relative = $Matches[2]
  if ($relative.StartsWith('/') -or $relative.Contains('..') -or $relative.Contains('\')) { Fail-Verification }
  if ($previous -ne "" -and [string]::CompareOrdinal($previous, $relative) -ge 0) { Fail-Verification }
  $previous = $relative
  $candidate = Join-Path $root ($relative.Replace('/', [IO.Path]::DirectorySeparatorChar))
  if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { Fail-Verification }
  $actual = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actual -cne $expected) { Fail-Verification }
  $listed++
}
if ($allFiles.Count -ne ($listed + 1)) { Fail-Verification }
Write-Output "verified_inert"
