"""
Prueba de rendimiento del Lab 5  (corre desde tu compu contra API Gateway)

PARTE 1 · Ingesta concurrente (POST /eventos)
    Manda requests con 1, 5, 10 y 20 clientes al mismo tiempo y mide latencia
    (promedio, p50, p95, p99) y throughput. Si la arquitectura escala, la
    latencia se mantiene parecida aunque suba la concurrencia.

PARTE 2 · Sin cache vs con cache (misma consulta a Redshift)
    GET /db/resumen  -> siempre consulta Redshift          (sin cache)
    GET /resumen     -> cache de API Gateway con TTL        (con cache)
    Primero en serie (como en el lab 4) y luego con 10 clientes concurrentes.

Uso:
    py carga.py                    # las dos partes
    py carga.py --solo cache       # solo la parte 2
    py carga.py --solo ingesta     # solo la parte 1

LÍMITES DE SEGURIDAD (presupuesto del Learner Lab):
    máx. 20 clientes concurrentes y 100 requests por nivel.
"""
import argparse
import os
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import api

MAX_CONCURRENCIA = 20
MAX_REQUESTS_POR_NIVEL = 100

# Colores ANSI (la terminal de VS Code los muestra)
AMARILLO, VERDE, ROJO, CIAN, GRIS, FIN = "\033[33m", "\033[32m", "\033[31m", "\033[36m", "\033[90m", "\033[0m"


def percentil(valores, p):
    if not valores:
        return 0.0
    v = sorted(valores)
    k = (len(v) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def eventos_prueba(n, boda_id):
    ahora = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return [{"evento_id": uuid.uuid4().hex, "boda_id": boda_id, "invitado_id": f"c-{uuid.uuid4().hex[:8]}",
             "nombre": "Invitado de prueba", "tipo": "invitacion", "ts": ahora, "lado": "novia"}
            for _ in range(n)]


def correr_nivel(funcion, concurrencia, total):
    """Ejecuta `total` llamadas con `concurrencia` hilos. -> (lista de (status, ms), segundos)"""
    inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrencia) as ex:
        resultados = list(ex.map(lambda _: funcion(), range(total)))
    return resultados, time.perf_counter() - inicio


def tabla_niveles(titulo, filas):
    print(f"\n{CIAN}=== {titulo} ==={FIN}\n")
    print(f"{'Clientes':>8} {'Requests':>8} {'OK':>5} {'Error':>5} {'Prom ms':>8} {'p50':>7} {'p95':>7} "
          f"{'p99':>7} {'Máx':>7} {'req/s':>7}")
    print(f"{'-' * 8:>8} {'-' * 8:>8} {'-' * 5:>5} {'-' * 5:>5} {'-' * 8:>8} {'-' * 7:>7} {'-' * 7:>7} "
          f"{'-' * 7:>7} {'-' * 7:>7} {'-' * 7:>7}")
    for f in filas:
        color = ROJO if f["error"] else ""
        print(f"{f['c']:>8} {f['n']:>8} {f['ok']:>5} {color}{f['error']:>5}{FIN if color else ''} "
              f"{f['prom']:>8.1f} {f['p50']:>7.1f} {f['p95']:>7.1f} {f['p99']:>7.1f} {f['max']:>7.1f} {f['rps']:>7.1f}")


def resumir(c, resultados, segundos, ok_status):
    ms = [m for s, m in resultados if s in ok_status]
    return {"c": c, "n": len(resultados), "ok": len(ms), "error": len(resultados) - len(ms),
            "prom": statistics.mean(ms) if ms else 0, "p50": percentil(ms, 50), "p95": percentil(ms, 95),
            "p99": percentil(ms, 99), "max": max(ms) if ms else 0, "rps": len(resultados) / segundos}


# ----------------------------------------------------------------- parte 1
def parte_ingesta(url, niveles, por_nivel, eventos_por_request):
    boda = "carga-" + datetime.now().strftime("%H%M%S")
    print(f"{AMARILLO}PARTE 1 · Ingesta concurrente: POST /eventos "
          f"({eventos_por_request} eventos por request, boda de prueba '{boda}'){FIN}")

    def una():
        s, _, ms = api.post(f"{url}/eventos", eventos_prueba(eventos_por_request, boda))
        return s, ms

    # Calentamiento: la primera llamada incluye el arranque en frío de la Lambda
    s, _, frio = api.post(f"{url}/eventos", eventos_prueba(1, boda))
    s2, _, tibio = api.post(f"{url}/eventos", eventos_prueba(1, boda))
    print(f"{GRIS}  1ª request (Lambda en frío): {frio:.0f} ms   ·   2ª request (Lambda caliente): {tibio:.0f} ms{FIN}")

    filas = []
    for c in niveles:
        res, seg = correr_nivel(una, c, por_nivel)
        f = resumir(c, res, seg, {202})
        f["eps"] = f["ok"] * eventos_por_request / seg
        filas.append(f)
        print(f"{GRIS}  {c:>2} clientes listo: p95 {f['p95']:.0f} ms, {f['rps']:.1f} req/s, "
              f"{f['eps']:.0f} eventos/s{FIN}")
    tabla_niveles("INGESTA: POST /eventos", filas)

    base, alto = filas[0], filas[-1]
    print(f"\n{VERDE}Throughput: {base['rps']:.1f} → {alto['rps']:.1f} req/s "
          f"(x{alto['rps'] / max(base['rps'], 0.01):.1f}) con {alto['c']} clientes; "
          f"p95: {base['p95']:.0f} → {alto['p95']:.0f} ms.{FIN}")
    errores = sum(f["error"] for f in filas)
    if errores:
        print(f"{ROJO}Hubo {errores} errores (posible límite de concurrencia de Lambda del Learner Lab).{FIN}")
    return filas


# ----------------------------------------------------------------- parte 2
def parte_cache(url, n):
    print(f"\n{AMARILLO}PARTE 2 · Misma consulta a Redshift: sin cache vs con cache{FIN}")

    # Sin cache, en serie
    sin = []
    print(f"\n{CIAN}=== SIN CACHE (GET /db/resumen) - {n} requests ==={FIN}\n")
    print(f"{'#':>3} {'Fuente':<20} {'ms':>8}")
    for i in range(1, n + 1):
        s, cuerpo, ms = api.get(f"{url}/db/resumen")
        sin.append(ms)
        print(f"{i:>3} {'redshift' if s == 200 else f'error {s}':<20} {ms:>8.1f}")

    # Con cache: la 1ª es miss (llena la cache), las demás hits
    print(f"\n{GRIS}Llenando la cache de API Gateway (1ª request a /resumen = miss)...{FIN}")
    s, primero, ms_miss = api.get(f"{url}/resumen")
    generado = primero.get("generado_en")
    print(f"{GRIS}  miss: {ms_miss:.1f} ms (generado_en {generado}){FIN}")

    con = []
    print(f"\n{CIAN}=== CON CACHE (GET /resumen) - mismos {n} requests ==={FIN}\n")
    print(f"{'#':>3} {'Fuente':<20} {'ms':>8}")
    for i in range(1, n + 1):
        s, cuerpo, ms = api.get(f"{url}/resumen")
        con.append(ms)
        fuente = "cache API Gateway" if cuerpo.get("generado_en") == generado else "redshift (expiró)"
        print(f"{i:>3} {fuente if s == 200 else f'error {s}':<20} {ms:>8.1f}")

    prom_sin, prom_con = statistics.mean(sin), statistics.mean(con)
    mejora = (1 - prom_con / prom_sin) * 100 if prom_sin else 0
    print(f"\n{CIAN}=== RESUMEN (en serie) ==={FIN}")
    print(f"Promedio SIN cache (/db/resumen): {prom_sin:8.1f} ms")
    print(f"Promedio CON cache (/resumen)   : {prom_con:8.1f} ms")
    print(f"{VERDE}Mejora con cache               : {mejora:.1f}% más rápido "
          f"(x{prom_sin / max(prom_con, 0.01):.1f}){FIN}")
    print(f"{GRIS}Prueba de que es la cache: todas las respuestas con cache traen el mismo "
          f"generado_en ({generado}), o sea, Redshift no se volvió a consultar.{FIN}")

    # Concurrente: aquí se ve la degradación sin cache
    c, total = 10, 30
    print(f"\n{GRIS}Ahora {total} requests con {c} clientes al mismo tiempo a cada endpoint...{FIN}")
    filas = []
    for ruta in ("/db/resumen", "/resumen"):
        res, seg = correr_nivel(lambda r=ruta: api.get(f"{url}{r}")[0::2], c, total)
        f = resumir(c, res, seg, {200})
        f["ruta"] = ruta
        filas.append(f)
    print(f"\n{CIAN}=== LECTURAS CONCURRENTES ({c} clientes, {total} requests) ==={FIN}\n")
    print(f"{'Endpoint':<14} {'OK':>4} {'Prom ms':>8} {'p50':>7} {'p95':>7} {'Máx':>7} {'req/s':>7}")
    for f in filas:
        print(f"{f['ruta']:<14} {f['ok']:>4} {f['prom']:>8.1f} {f['p50']:>7.1f} {f['p95']:>7.1f} "
              f"{f['max']:>7.1f} {f['rps']:>7.1f}")
    print(f"\n{VERDE}Con {c} clientes: p95 sin cache {filas[0]['p95']:.0f} ms vs con cache "
          f"{filas[1]['p95']:.0f} ms; throughput {filas[0]['rps']:.1f} vs {filas[1]['rps']:.1f} req/s.{FIN}")


def main():
    os.system("")  # activa colores ANSI en la consola de Windows
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--solo", choices=["ingesta", "cache"])
    p.add_argument("--niveles", default="1,5,10,20", help="clientes concurrentes por nivel")
    p.add_argument("--requests", type=int, default=60, help="requests por nivel de ingesta")
    p.add_argument("--eventos-por-request", type=int, default=10)
    p.add_argument("--n-cache", type=int, default=8, help="requests en serie para la comparación de cache")
    args = p.parse_args()

    niveles = [int(x) for x in args.niveles.split(",")]
    if max(niveles) > MAX_CONCURRENCIA or args.requests > MAX_REQUESTS_POR_NIVEL:
        sys.exit(f"Límite: {MAX_CONCURRENCIA} clientes y {MAX_REQUESTS_POR_NIVEL} requests por nivel.")
    if not 1 <= args.eventos_por_request <= 25:
        sys.exit("--eventos-por-request entre 1 y 25")

    url = api.url_base()
    print(f"API: {url}\n")
    if args.solo in (None, "ingesta"):
        parte_ingesta(url, niveles, args.requests, args.eventos_por_request)
    if args.solo in (None, "cache"):
        parte_cache(url, args.n_cache)


if __name__ == "__main__":
    main()
