"""
Lambda "consulta": GET /resumen y GET /db/resumen  ->  Redshift

Las dos rutas ejecutan EXACTAMENTE la misma consulta. La diferencia es de
arquitectura:

  GET /db/resumen  siempre llega hasta Redshift (peor caso, sin cache).
  GET /resumen     tiene la cache de API Gateway: la primera vez llega aquí
                   (miss) y durante el TTL API Gateway responde solo (hit),
                   sin invocar esta Lambda ni a Redshift.

Así se protege la base columnar (pensada para análisis, no para miles de
lecturas iguales) y se ahorra cómputo de Redshift.
"""
import json
import time
from datetime import datetime, timezone

import redshift as rs

RESUMEN = """
SELECT
    (SELECT MAX(boda_id) FROM v_boda_actual)                                        AS boda_id,
    COUNT(*)                                                                         AS invitados,
    SUM(CASE WHEN estado = 'confirmado' THEN 1 ELSE 0 END)                           AS confirmados,
    SUM(CASE WHEN estado = 'cancelado'  THEN 1 ELSE 0 END)                           AS cancelados,
    SUM(CASE WHEN estado = 'pendiente'  THEN 1 ELSE 0 END)                           AS pendientes,
    SUM(CASE WHEN estado = 'confirmado' AND mesa IS NULL THEN 1 ELSE 0 END)          AS sin_mesa,
    SUM(CASE WHEN llego THEN 1 ELSE 0 END)                                           AS llegaron,
    SUM(CASE WHEN llego AND estado <> 'confirmado' THEN 1 ELSE 0 END)                AS colados,
    SUM(CASE WHEN estado = 'confirmado' AND menu = 'res' THEN 1 ELSE 0 END)          AS menu_res,
    SUM(CASE WHEN estado = 'confirmado' AND menu = 'pollo' THEN 1 ELSE 0 END)        AS menu_pollo,
    SUM(CASE WHEN estado = 'confirmado' AND menu = 'vegetariano' THEN 1 ELSE 0 END)  AS menu_vegetariano,
    SUM(CASE WHEN estado = 'confirmado' AND menu = 'infantil' THEN 1 ELSE 0 END)     AS menu_infantil,
    SUM(CASE WHEN estado = 'confirmado' AND restriccion IS NOT NULL THEN 1 ELSE 0 END) AS con_restriccion
FROM v_invitados_actual
"""


def respuesta(status: int, cuerpo: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps(cuerpo, ensure_ascii=False, default=str),
    }


def handler(event, context):
    ruta = event.get("resource") or event.get("path") or "?"
    inicio = time.perf_counter()
    try:
        filas = rs.consultar(RESUMEN)
        resumen = filas[0] if filas else {}
        estado = 200
    except rs.ErrorRedshift as err:
        msg = str(err)
        if "does not exist" in msg:  # todavía no llega ningún evento
            resumen, estado = {"nota": "aún no hay eventos guardados"}, 200
        else:
            print(json.dumps({"evento": "error", "error": msg[:300]}))
            return respuesta(502, {"error": "Redshift no respondió", "detalle": msg[:200]})

    ms = round((time.perf_counter() - inicio) * 1000, 1)
    print(json.dumps({"evento": "consulta", "ruta": ruta, "redshift_ms": ms}))
    return respuesta(estado, {
        "endpoint": ruta,
        "fuente": "redshift",
        "redshift_ms": ms,
        "generado_en": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "request_id": getattr(context, "aws_request_id", None),
        "resumen": resumen,
    })
