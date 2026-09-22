# wrk2 en Docker

Compila una sola vez:

```powershell
cd loadtest
docker build -t lab4-wrk2 .
cd ..
```

Corridas de load test (reemplaza $ALB_URL por tu URL real, o define la
variable como en los pasos anteriores):

```powershell
# Corrida A - endpoint SIN cache (/db/item nunca toca Redis)
docker run --rm lab4-wrk2 -t4 -c50 -d30s -R100 --latency "$ALB_URL/db/item/1"

# Precalentar el cache del endpoint CON cache (1 sola vez)
Invoke-RestMethod "$ALB_URL/item/1" | Out-Null

# Corrida B - endpoint CON cache (/item sirve desde Redis)
docker run --rm lab4-wrk2 -t4 -c50 -d30s -R100 --latency "$ALB_URL/item/1"
```

Flags: -t4 = 4 threads, -c50 = 50 conexiones, -d30s = dura 30s,
-R100 = 100 requests/seg constantes, --latency = imprime percentiles.
Si tu Lambda/RDS no aguanta 100 req/s bájalo a -R50; wrk2 igual mide la
latencia real aunque no alcance el rate configurado.
