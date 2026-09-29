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
    [ValidateSet("start", "stop", "status", "restart", "watchdog", "supervise", "install", "uninstall", "autostart")]
    [string]$Action = "status",

    [int]$MaxRestarts = 20,
    [int]$IntervalSeconds = 60
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "bot-service"
$Log = Join-Path $LogDir "bot.log"
$ErrLog = Join-Path $LogDir "bot.err"
$TaskName = "DocParserTelegramBot"
$WatchdogTask = "DocParserTelegramBotWatchdog"

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

    "watchdog" {
        # A dead bot means clients cannot send anything, and nobody is watching
        # the process, so this is run on a schedule and starts it if it is gone.
        $running = @(Get-BotProcess)
        if ($running.Count -eq 0) {
            Write-Host "Бот не запущен, поднимаю."
            try {
                Start-Bot | Out-Null
            } catch {
                # A failed restart must not fail the scheduled task loudly every
                # five minutes; the reason is already in the error log.
                Write-Host "Не удалось поднять: $($_.Exception.Message)"
                exit 1
            }
        } else {
            Write-Host "Бот жив, PID $($running[0].Id). Ничего делать не нужно."
        }
    }

    "supervise" {
        # The supervisor is what makes the bot survive a crash without anyone
        # watching it. It needs no administrator rights, unlike a scheduled
        # task, so it can be started from the Startup folder.
        Write-Host "Надзиратель запущен. Проверка каждые $IntervalSeconds с. Ctrl+C — остановить надзиратель."
        while ($true) {
            $running = @(Get-BotProcess)
            if ($running.Count -eq 0) {
                Write-Host "$(Get-Date -Format 'HH:mm:ss') бот не найден, поднимаю."
                try {
                    Start-Bot | Out-Null
                } catch {
                    Write-Host "$(Get-Date -Format 'HH:mm:ss') не удалось: $($_.Exception.Message)"
                }
            }
            Start-Sleep -Seconds $IntervalSeconds
        }
    }

    "autostart" {
        # A shortcut in the Startup folder needs no elevation, so this works on
        # a normal account. Registering a scheduled task does need admin, which
        # is why `install` exists separately and is not required.
        $startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
        New-Item -ItemType Directory -Force -Path $startup | Out-Null
        $cmd = Join-Path $startup "docparser-bot.cmd"
        $self = Join-Path $PSScriptRoot "bot_service.ps1"

        # PowerShell escapes a quote with a backtick, not a backslash, so the
        # line is assembled from single-quoted parts. The result is cmd syntax,
        # which is where the backslash-quotes belong.
        $line = 'start "" /min powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden ' +
                '-File "' + $self + '" supervise'

        @(
            "@echo off",
            "rem Keeps the DocParser Telegram bot alive: starts it at logon and",
            "rem restarts it if it dies. No administrator rights needed.",
            $line
        ) | Set-Content -Path $cmd -Encoding ASCII

        Write-Host "Автозагрузка настроена: $cmd"
        Write-Host "Бот поднимется при следующем входе в Windows."
    }

    "install" {
        # PowerShell variable names are case-insensitive, so this must not be
        # called $action: that would overwrite the $Action parameter, and the
        # registered command ended up pointing at a file named after the verb.
        $scriptPath = Join-Path $PSScriptRoot "bot_service.ps1"

        # 1. Start the bot on every logon.
        # Register-ScheduledTask wants a CimInstance for -Action, so a plain
        # string is rejected with "cannot convert value of type Action".
        $startAction = New-ScheduledTaskAction `
            -Execute "powershell.exe" `
            -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`" start"
        $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($existing) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }

        $trigger = New-ScheduledTaskTrigger -AtLogOn
        $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $TaskName -Action $startAction -Trigger $trigger `
            -Principal $principal -Description "DocParser Telegram bot (start at logon)" -Force | Out-Null
        Write-Host "Задача '$TaskName': бот стартует при каждом входе в Windows."

        # 2. Watchdog, so a crash does not leave clients with a silent bot.
        $watchAction = New-ScheduledTaskAction `
            -Execute "powershell.exe" `
            -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`" watchdog"
        if (Get-ScheduledTask -TaskName $WatchdogTask -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $WatchdogTask -Confirm:$false
        }
        # Windows PowerShell 5.1 has no New-ScheduledTaskRepetition, so a
        # repeating trigger is a -Once trigger given an interval and a long
        # duration. Ten years is the practical stand-in for "indefinitely".
        $watchTrigger = New-ScheduledTaskTrigger `
            -Once `
            -At (Get-Date).AddMinutes(1) `
            -RepetitionInterval (New-TimeSpan -Minutes 5) `
            -RepetitionDuration (New-TimeSpan -Days 3650)
        Register-ScheduledTask -TaskName $WatchdogTask -Action $watchAction -Trigger $watchTrigger `
            -Principal $principal -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew) `
            -Description "DocParser Telegram bot (restart if it died)" -Force | Out-Null
        Write-Host "Задача '$WatchdogTask': каждые 5 минут проверит, что бот жив, и поднимет его."
    }

    "uninstall" {
        foreach ($name in @($TaskName, $WatchdogTask)) {
            if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
                Unregister-ScheduledTask -TaskName $name -Confirm:$false
                Write-Host "Задача '$name' удалена."
            } else {
                Write-Host "Задачи '$name' нет."
            }
        }
    }
}
