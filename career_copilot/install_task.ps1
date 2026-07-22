# Windows PowerShell Script to Register Career Copilot as a background daily scheduled task
# Run this script as Administrator from the adk-workspace root directory.

$WorkspaceRoot = (Get-Location).Path
$ScriptPath = Join-Path $WorkspaceRoot "career_copilot\scheduler.py"
$VenvPython = Join-Path $WorkspaceRoot ".venv\Scripts\python.exe"

# Make sure scripts/binaries exist
if (-not (Test-Path $ScriptPath)) {
    Write-Error "Error: Could not find 'career_copilot\scheduler.py' in the current directory."
    Exit 1
}

if (-not (Test-Path $VenvPython)) {
    Write-Error "Error: Virtual environment python executable not found at '$VenvPython'."
    Exit 1
}

$TaskName = "CareerCopilotDailyDigest"
$Query = "Python Developer"
$Time = "09:00"

# Define the Scheduled Task Action
$Action = New-ScheduledTaskAction -Execute $VenvPython -Argument "-m career_copilot.scheduler --query `"$Query`" --time `"$Time`"" -WorkingDirectory $WorkspaceRoot

# Define the Daily Trigger (Runs at the specified time every day)
$Trigger = New-ScheduledTaskTrigger -Daily -At (Get-Date $Time)

# Define task settings (allow running on battery power, don't stop task, start when available)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Write-Host "Registering daily scheduled task '$TaskName' to run at $Time in the background..."
Write-Host "Working Directory: $WorkspaceRoot"

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Executes the Career Copilot job search and daily email/Telegram digest pipeline." -Force

Write-Host "`n[Success] Native scheduled task '$TaskName' registered successfully."
Write-Host "You can verify and monitor this task inside Windows Task Scheduler."
