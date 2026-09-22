# Lab4 - Demo automatica: compara el endpoint SIN cache (/db/item) contra
# el endpoint CON cache (/item), usando los mismos ids en los dos.
#
# Uso:
#   cd lab4
#   .\demo.ps1
#
# Si PowerShell bloquea el script por la politica de ejecucion, corre:
#   powershell -ExecutionPolicy Bypass -File .\demo.ps1

param(
    [int[]]$Ids = (1..8)
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "Obteniendo ALB URL desde Terraform..." -ForegroundColor DarkGray
$AlbUrl = terraform output -raw alb_url
Write-Host "ALB URL: $AlbUrl`n" -ForegroundColor DarkGray

Write-Host "=== SIN CACHE (/db/item) - $($Ids.Count) requests ===" -ForegroundColor Yellow
$sinCache = foreach ($i in $Ids) {
    $t = Measure-Command { $r = Invoke-RestMethod "$AlbUrl/db/item/$i" }
    [PSCustomObject]@{ Id = $i; Source = $r.source; Ms = [math]::Round($t.TotalMilliseconds, 1) }
}
$sinCache | Format-Table -AutoSize
$avgSinCache = ($sinCache | Measure-Object -Property Ms -Average).Average

Write-Host "Precalentando el cache para los mismos ids..." -ForegroundColor DarkGray
foreach ($i in $Ids) { Invoke-RestMethod "$AlbUrl/item/$i" | Out-Null }

Write-Host "`n=== CON CACHE (/item) - mismos ids ===" -ForegroundColor Green
$conCache = foreach ($i in $Ids) {
    $t = Measure-Command { $r = Invoke-RestMethod "$AlbUrl/item/$i" }
    [PSCustomObject]@{ Id = $i; Source = $r.source; Ms = [math]::Round($t.TotalMilliseconds, 1) }
}
$conCache | Format-Table -AutoSize
$avgConCache = ($conCache | Measure-Object -Property Ms -Average).Average

Write-Host "`n=== RESUMEN ===" -ForegroundColor Cyan
Write-Host ("Promedio SIN cache (/db/item): {0:N1} ms" -f $avgSinCache)
Write-Host ("Promedio CON cache (/item)   : {0:N1} ms" -f $avgConCache)
$mejora = [math]::Round((1 - ($avgConCache / $avgSinCache)) * 100, 1)
Write-Host ("Mejora con cache             : {0}% mas rapido" -f $mejora) -ForegroundColor Green
