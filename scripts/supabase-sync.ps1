# Supabase local → cloud sync script
# Runs nightly at 11:30 PM EST via Windows Task Scheduler
# Pushes local migrations to the linked cloud project

$ErrorActionPreference = "Stop"
$logFile = "$env:USERPROFILE\.astridr\logs\supabase-sync.log"

# Ensure log directory exists
New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

try {
    Set-Location "$env:USERPROFILE\astridr-repo"

    # Read access token from environment variable
    if (-not $env:SUPABASE_ACCESS_TOKEN) {
        throw "SUPABASE_ACCESS_TOKEN environment variable is not set"
    }

    # Push local migrations to cloud
    $output = npx supabase db push --linked 2>&1
    Add-Content $logFile "[$timestamp] SUCCESS: $output"

    Write-Host "Sync complete at $timestamp"
}
catch {
    Add-Content $logFile "[$timestamp] ERROR: $_"
    Write-Host "Sync failed: $_" -ForegroundColor Red
    exit 1
}
