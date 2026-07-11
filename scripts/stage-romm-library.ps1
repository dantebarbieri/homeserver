[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Source = 'D:\iCloudDrive\ROMs',
    [string]$Destination = 'D:\RomM-Staging\roms'
)

$ErrorActionPreference = 'Stop'

$platforms = [ordered]@{
    'Arcade'          = @{ Slug = 'arcade'; Extensions = @('.zip') }
    'GameBoy'         = @{ Slug = 'gb';     Extensions = @('.zip', '.gb') }
    'GameBoy Advance' = @{ Slug = 'gba';    Extensions = @('.zip', '.gba', '.rar', '.7z') }
    'GameBoy Color'   = @{ Slug = 'gbc';    Extensions = @('.zip', '.gbc') }
    'N64'             = @{ Slug = 'n64';    Extensions = @('.zip', '.z64', '.n64', '.v64', '.7z') }
    'NDS'             = @{ Slug = 'nds';    Extensions = @('.zip', '.nds', '.7z') }
    'NES'             = @{ Slug = 'nes';    Extensions = @('.zip', '.nes', '.7z') }
    'SNES'            = @{ Slug = 'snes';   Extensions = @('.zip', '.sfc', '.smc', '.7z') }
}

if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
    throw "ROM library not found: $Source"
}

$planned = @()
$targets = @{}

foreach ($entry in $platforms.GetEnumerator()) {
    $sourceDirectory = Join-Path $Source $entry.Key
    if (-not (Test-Path -LiteralPath $sourceDirectory -PathType Container)) {
        throw "Expected platform directory not found: $sourceDirectory"
    }

    $files = Get-ChildItem -LiteralPath $sourceDirectory -File -Recurse -Force |
        Where-Object { $entry.Value.Extensions -contains $_.Extension.ToLowerInvariant() }

    foreach ($file in $files) {
        $targetDirectory = Join-Path $Destination $entry.Value.Slug
        $targetPath = Join-Path $targetDirectory $file.Name

        if ($targets.ContainsKey($targetPath)) {
            throw "Flattening collision: '$($file.FullName)' and '$($targets[$targetPath])' both map to '$targetPath'"
        }

        $targets[$targetPath] = $file.FullName
        $planned += [pscustomobject]@{
            Source = $file
            TargetDirectory = $targetDirectory
            TargetPath = $targetPath
        }
    }
}

$offline = @(
    $planned | Where-Object {
        $_.Source.Attributes -band [System.IO.FileAttributes]::Offline
    }
)

if ($offline.Count -gt 0) {
    throw "$($offline.Count) ROM files are still cloud-only. In File Explorer, mark '$Source' as 'Always keep on this device', wait for iCloud to finish, and rerun."
}

$copied = 0
$skipped = 0
$written = 0
$total = $planned.Count

foreach ($item in $planned) {
    $copied++
    Write-Progress -Activity 'Staging RomM library' -Status "$copied of $total" -PercentComplete (($copied / $total) * 100)

    if (Test-Path -LiteralPath $item.TargetPath -PathType Leaf) {
        $existing = Get-Item -LiteralPath $item.TargetPath
        if ($existing.Length -ne $item.Source.Length) {
            throw "Existing staged file has a different size: $($item.TargetPath)"
        }

        $skipped++
        continue
    }

    if ($PSCmdlet.ShouldProcess($item.Source.FullName, "Copy to $($item.TargetPath)")) {
        New-Item -ItemType Directory -Force -Path $item.TargetDirectory | Out-Null
        Copy-Item -LiteralPath $item.Source.FullName -Destination $item.TargetPath
        $written++
    }
}

Write-Progress -Activity 'Staging RomM library' -Completed

$bytes = ($planned | ForEach-Object { $_.Source.Length } | Measure-Object -Sum).Sum
if ($WhatIfPreference) {
    Write-Output "Would stage $total ROM files ($([math]::Round($bytes / 1GB, 2)) GiB) under '$Destination'."
} else {
    Write-Output "Staged $written ROM files under '$Destination'."
}
if ($skipped -gt 0) {
    Write-Output "Skipped $skipped files that were already staged with the expected size."
}
