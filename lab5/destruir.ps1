# Apaga y BORRA todo lo del lab5 para no gastar presupuesto.
#   .\destruir.ps1
# Al final revisa la cuenta para confirmar que no quedó nada cobrando.
$ErrorActionPreference = "Continue"
$raiz = $PSScriptRoot

Write-Host "`n[1/3] Apagando Grafana local..." -ForegroundColor Cyan
Push-Location "$raiz\dashboard"
docker compose down 2>$null
Pop-Location

Write-Host "`n[2/3] terraform destroy (el clúster de Redshift tarda unos minutos en borrarse)..." -ForegroundColor Cyan
Push-Location "$raiz\infra"
terraform destroy -auto-approve
if ($LASTEXITCODE -ne 0) {
    Write-Host "El destroy falló; reintentando en 2 min..." -ForegroundColor Yellow
    Start-Sleep -Seconds 120
    terraform destroy -auto-approve
}
$restantes = terraform state list
Pop-Location

if ($restantes) {
    Write-Host "`nOJO: Terraform todavía tiene recursos en su state:" -ForegroundColor Red
    $restantes
    Write-Host "Vuelve a correr .\destruir.ps1 en unos minutos." -ForegroundColor Red
} else {
    Write-Host "`nTerraform: 0 recursos. Todo lo del lab5 está borrado." -ForegroundColor Green
}

Write-Host "`n[3/3] Revisando la cuenta completa..." -ForegroundColor Cyan
# Busca un Python que funcione (el alias de la Microsoft Store a veces falla)
$py = $null
foreach ($cand in @("py", "python3", "python")) {
    try { & $cand --version *> $null; if ($LASTEXITCODE -eq 0) { $py = $cand; break } } catch {}
}
if ($py) {
    & $py "$raiz\verificar_cuenta.py"
} else {
    Write-Host "No encontré Python; corre: py verificar_cuenta.py" -ForegroundColor Yellow
}
