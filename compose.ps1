# Запуск docker compose с env/docker.env (подстановка ${VAR} в compose-файле).
# Использование: .\compose.ps1 up --build | .\compose.ps1 -e .\env\docker.env ps

$defaultEnvFile = ".\env\docker.env"
$envFile = if ($env:ENV_FILE) { $env:ENV_FILE } else { $defaultEnvFile }

$scriptArgs = @($args)
$filtered = New-Object System.Collections.Generic.List[string]
$skipNext = $false
for ($i = 0; $i -lt $scriptArgs.Count; $i++) {
    if ($skipNext) {
        $skipNext = $false
        continue
    }
    if ($scriptArgs[$i] -eq "-e" -and ($i + 1) -lt $scriptArgs.Count) {
        $envFile = $scriptArgs[$i + 1]
        $skipNext = $true
        continue
    }
    $filtered.Add($scriptArgs[$i])
}

docker compose --env-file $envFile @filtered
exit $LASTEXITCODE
