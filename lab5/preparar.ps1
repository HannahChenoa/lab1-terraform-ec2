# Después de "terraform apply": genera la config para el simulador, la prueba de carga y Grafana.
#   .\preparar.ps1
$ErrorActionPreference = "Stop"
$raiz = $PSScriptRoot

Push-Location "$raiz\infra"
try {
    $o = terraform output -json | ConvertFrom-Json
} finally {
    Pop-Location
}

# UTF-8 sin BOM (Python y Docker no se llevan bien con el BOM de PowerShell 5)
$utf8 = New-Object System.Text.UTF8Encoding($false)

$sensores = @{
    region  = $o.region.value
    api_url = $o.api_url.value
} | ConvertTo-Json
[System.IO.File]::WriteAllText("$raiz\sensores\outputs.json", $sensores, $utf8)

$envGrafana = @"
REDSHIFT_CLUSTER=$($o.redshift_cluster.value)
REDSHIFT_DATABASE=$($o.redshift_database.value)
REDSHIFT_SECRET_ARN=$($o.redshift_secret_arn.value)
REDSHIFT_SECRET_NAME=$($o.redshift_secret_name.value)
"@
[System.IO.File]::WriteAllText("$raiz\dashboard\.env", $envGrafana, $utf8)

Write-Host "OK  sensores\outputs.json y dashboard\.env generados" -ForegroundColor Green
Write-Host "    API Gateway: $($o.api_url.value)"
Write-Host "    Redshift:    $($o.redshift_cluster.value) / $($o.redshift_database.value)"
Write-Host "    CloudWatch:  $($o.cloudwatch_dashboard_url.value)"
