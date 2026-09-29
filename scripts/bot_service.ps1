<#
    Start the Telegram bot as a background service that restarts on its own.

    The bot is the whole product for a client, so it must come back after a
    crash and after a reboot. Only one process may poll a single token, so
    this refuses to start a second copy rather than letting the two go deaf on
    Telegram's 409.

        powershell -ExecutionPolicy Bypass -File scripts\bot_service.ps1 start
        powershell -ExecutionPolicy Bypass -File scripts\bot_service.ps1 status
        powershell -ExecutionPolicy Bypass -File scripts\bot_service.ps1 stop
        powershell -ExecutionPolicy Bypass -File scripts\bot_service.ps1 install   # at login
        powershell -ExecutionPolicy Bypass -File scripts\bot_service.ps1 uninstall
#>

param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "status", "restart", "install", "uninstall")]
    [string]$Action = "status",

    [int]$MaxRestarts = 20
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "bot-service"
$Log = Join-Path $LogDir "bot.log"
$ErrLog = Join-Path $LogDir "bot.err"
$TaskName = "DocParserTelegramBot"

function Resolve-Python {
    # pythonw runs the bot with no console window. It has to come from the same
    # installation as `python`, because the WindowsApps shim on PATH is a
    # launcher for a different interpreter that does not have the project's
    # packages, and starting that produced "No module named 'telegram'".
    $candidates = @()

    $venv = Join-Path $Root ".venv\Scripts\pythonw.exe"
    if (Test-Path $venv) { $candidates += $venv }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        $sibling = Join-Path (Split-Path -Parent $python.Source) "pythonw.exe"
        if (Test-Path $sibling) { $candidates += $sibling }
        $candidates += $python.Source
    }

    foreach ($candidate in $candidates) {
        # Accept the interpreter only if it can actually import the bot.
        $probe = & $candidate -c "import telegram, PIL, structlog" 2>&1
        if ($LASTEXITCODE -eq 0) { return $candidate }
    }

    throw "Не найден Python с зависимостями бота. Установи: pip install -r requirements-bot.txt"
}

$Python = Resolve-Python

function Get-BotProcess {
    Get-CimInstance Win32_Process -Filter "Name='$([System.IO.Path]::GetFileName($Python))'" |
        Where-Object { $_.CommandLine -like "*app.bot*" } |
        ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
}

function Assert-NoDuplicate {
    $running = @(Get-BotProcess)
    if ($running.Count -gt 0) {
        throw "Бот уже запущен (PID $($running[0].Id)). Останови его: stop"
    }
}

function Start-Bot {
    Assert-NoDuplicate
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    Remove-Item $Log, $ErrLog -ErrorAction SilentlyContinue

    $process = Start-Process -FilePath $Python `
        -ArgumentList "-m", "app.bot" `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $Log `
        -RedirectStandardError $ErrLog `
        -WindowStyle Hidden `
        -PassThru

    # A bot that dies at once has failed, and a wrapper that keeps restarting
    # it would just burn through the restart budget.
    Start-Sleep -Seconds 8
    if (-not (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)) {
        $why = if (Test-Path $ErrLog) { (Get-Content $ErrLog -Tail 5) -join " " } else { "нет вывода" }
        throw "Бот упал сразу после старта. Причина: $why"
    }

    Write-Host "Бот запущен, PID $($process.Id). Логи: $LogDir"
    return $process.Id
}

switch ($Action) {
    "start" { Start-Bot | Out-Null }

    "stop" {
        $running = @(Get-BotProcess)
        if ($running.Count -eq 0) { Write-Host "Бот не запущен."; break }
        $running | ForEach-Object { Stop-Process -Id $_.Id -Force }
        Write-Host "Остановлено процессов: $($running.Count)"
    }

    "restart" {
        & $PSScriptPath "bot_service.ps1" stop
        Start-Sleep -Seconds 2
        Start-Bot | Out-Null
    }

    "status" {
        $running = @(Get-BotProcess)
        if ($running.Count -eq 0) {
            Write-Host "Бот НЕ запущен. Клиенты не смогут прислать документы."
            Write-Host "Запустить: scripts\bot_service.ps1 start"
        } else {
            $p = $running[0]
            Write-Host "Бот работает, PID $($p.Id), запущен $($p.StartTime)"
        }
        if (Test-Path $LogDir) {
            $errors = @(Get-Content $ErrLog -ErrorAction SilentlyContinue |
                        Select-String -Pattern "ERROR|Traceback")
            if ($errors.Count -gt 0) {
                Write-Host "В логе ошибок: $($errors.Count). Последние:"
                $errors | Select-Object -Last 3 | ForEach-Object { Write-Host "  $_" }
            }
        }
    }

    "install" {
        $action = Join-Path $PSScriptRoot "bot_service.ps1"
        $command = "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$action`" start"
        $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($existing) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }

        $trigger = New-ScheduledTaskTrigger -AtLogOn
        $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $TaskName -Action $command -Trigger $trigger `
            -Principal $principal -Description "DocParser Telegram bot" -Force | Out-Null

        Write-Host "Задача '$TaskName' создана: бот стартует при каждом входе в Windows."
    }

    "uninstall" {
        $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($existing) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Host "Задача удалена."
        } else {
            Write-Host "Задачи нет."
        }
    }
}
