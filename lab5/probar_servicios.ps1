# Revisa qué servicios del lab permite esta cuenta del Learner Lab (antes de terraform apply).
#   .\probar_servicios.ps1
# Sirve también como evidencia para el reporte (sale tu correo del Learner Lab).
$ErrorActionPreference = "Continue"
$p = @("--profile", "academy", "--region", "us-east-1", "--output", "json")

function Probar($nombre, [scriptblock]$cmd) {
    $salida = & $cmd 2>&1 | Out-String
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK]   $nombre" -ForegroundColor Green
    } else {
        $msg = ($salida -split "`n" | Where-Object { $_ -match "error|Exception|denied|not authorized" } | Select-Object -First 1)
        Write-Host "  [NO]   $nombre" -ForegroundColor Red
        if ($msg) { Write-Host "         $($msg.Trim())" -ForegroundColor DarkGray }
    }
    return ($LASTEXITCODE -eq 0), $salida
}

Write-Host "`n== Identidad ==" -ForegroundColor Cyan
$id = aws sts get-caller-identity @p | ConvertFrom-Json
Write-Host "  Cuenta: $($id.Account)"
Write-Host "  Usuario: $($id.Arn)"

Write-Host "`n== Servicios del lab ==" -ForegroundColor Cyan
Probar "API Gateway (REST)"        { aws apigateway get-rest-apis @p } | Out-Null
Probar "Kinesis Data Streams"       { aws kinesis list-streams @p } | Out-Null
Probar "SQS"                        { aws sqs list-queues @p } | Out-Null
Probar "Lambda"                     { aws lambda list-functions --max-items 1 @p } | Out-Null
Probar "Redshift (clústeres)"       { aws redshift describe-clusters @p } | Out-Null
Probar "Redshift Serverless"        { aws redshift-serverless list-workgroups @p } | Out-Null
Probar "Redshift Data API"          { aws redshift-data list-statements --max-items 1 @p } | Out-Null
Probar "Secrets Manager"            { aws secretsmanager list-secrets --max-items 1 @p } | Out-Null

$lim = aws lambda get-account-settings @p | ConvertFrom-Json
Write-Host "  Límite de Lambdas concurrentes de la cuenta: $($lim.AccountLimit.ConcurrentExecutions)"

Write-Host "`n== AWS Managed Grafana ==" -ForegroundColor Cyan
Probar "Listar workspaces de Grafana" { aws grafana list-workspaces @p } | Out-Null
Probar "IAM Identity Center (SSO) habilitado" { aws sso-admin list-instances @p } | Out-Null
$sso = aws sso-admin list-instances @p 2>$null | ConvertFrom-Json
if ($sso -and $sso.Instances.Count -eq 0) {
    Write-Host "         No hay instancia de IAM Identity Center en la cuenta (Managed Grafana la necesita para iniciar sesión)" -ForegroundColor DarkGray
}

$rol = "arn:aws:iam::$($id.Account):role/LabRole"
Write-Host "  Intentando crear un workspace de prueba (lab5-prueba-grafana)..."
$ok, $salida = Probar "Crear workspace de Managed Grafana" {
    aws grafana create-workspace --workspace-name lab5-prueba-grafana `
        --account-access-type CURRENT_ACCOUNT --authentication-providers AWS_SSO `
        --permission-type CUSTOMER_MANAGED --workspace-role-arn $rol `
        --workspace-data-sources REDSHIFT CLOUDWATCH @p
}
if ($ok) {
    $ws = $salida | ConvertFrom-Json
    Write-Host "  Se creó $($ws.workspace.id). Lo borro para no dejar nada prendido..." -ForegroundColor Yellow
    aws grafana delete-workspace --workspace-id $ws.workspace.id @p | Out-Null
} else {
    Write-Host "`n  Managed Grafana NO está disponible en esta cuenta del Learner Lab." -ForegroundColor Yellow
    Write-Host "  Toma captura de esta pantalla para la sección 'Problemas encontrados' del reporte." -ForegroundColor Yellow
    Write-Host "  El lab usa Grafana OSS (la misma herramienta) en Docker, conectado a Redshift y CloudWatch." -ForegroundColor Yellow
}
Write-Host ""
