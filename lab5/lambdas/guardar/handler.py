"""
[4] Lambda "guardar":  SQS  ->  Amazon Redshift (columnar)

La dispara SQS con lotes de hasta 100 eventos ya procesados. Los inserta en la
tabla `eventos` con UN solo INSERT de varias filas por lote: en una base
columnar se carga en lotes, no fila por fila.

Usa la Redshift Data API (HTTPS): sin VPC, sin driver y sin conexiones abiertas.

Si el INSERT del lote falla, se reintenta fila por fila para que solo los
mensajes malos regresen a la cola (ReportBatchItemFailures); después de 3
intentos SQS los manda a la DLQ.
"""
import json
from datetime import datetime, timezone

import esquema
import redshift as rs

_esquema_listo = False  # se crea una vez por contenedor (warm start)

COLUMNAS = ["evento_id", "boda_id", "invitado_id", "nombre", "tipo", "ts", "lado", "respuesta",
            "canal", "menu", "restriccion", "ultimo_momento", "mesa", "asiento", "metodo",
            "alerta", "motivo_alerta", "latencia_ingesta_ms"]


def asegurar_esquema() -> None:
    global _esquema_listo
    if not _esquema_listo:
        rs.ejecutar_varias(esquema.TODO)
        _esquema_listo = True
        print(json.dumps({"evento": "esquema_listo"}))


def ts_redshift(iso: str) -> str:
    """'2026-10-17T21:03:04.123Z' -> '2026-10-17 21:03:04.123' (UTC, TIMESTAMP sin zona)."""
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    return t.strftime("%Y-%m-%d %H:%M:%S.") + f"{t.microsecond // 1000:03d}"


def fila_sql(e: dict) -> str:
    d = e.get("detalle", {})
    valores = [
        rs.texto(e["evento_id"], 64),
        rs.texto(e["boda_id"], 64),
        rs.texto(e["invitado_id"], 32),
        rs.texto(e.get("nombre"), 128),
        rs.texto(e["tipo"], 16),
        rs.texto(ts_redshift(e["ts"])),
        rs.texto(d.get("lado"), 16),
        rs.texto(d.get("respuesta"), 16),
        rs.texto(d.get("canal"), 16),
        rs.texto(d.get("menu"), 16),
        rs.texto(d.get("restriccion"), 64),
        rs.booleano(d.get("ultimo_momento")),
        rs.entero(d.get("mesa")),
        rs.entero(d.get("asiento")),
        rs.texto(d.get("metodo"), 16),
        rs.booleano(e.get("alerta")),
        rs.texto(e.get("motivo_alerta") or None, 256),
        rs.entero(e.get("latencia_ingesta_ms")),
    ]
    return "(" + ", ".join(valores) + ")"


def insertar(filas: list[str]) -> None:
    rs.ejecutar(f"INSERT INTO eventos ({', '.join(COLUMNAS)}) VALUES " + ",\n".join(filas))


def handler(event, context):
    records = event["Records"]
    fallidos: list[str] = []
    filas: list[tuple[str, str]] = []  # (messageId, fila SQL)

    for r in records:
        try:
            filas.append((r["messageId"], fila_sql(json.loads(r["body"]))))
        except (ValueError, KeyError, TypeError) as err:
            print(json.dumps({"evento": "mensaje_invalido", "id": r["messageId"], "error": str(err)}))
            fallidos.append(r["messageId"])

    try:
        asegurar_esquema()
    except Exception as err:  # Redshift no disponible: todo el lote regresa a la cola
        print(json.dumps({"evento": "sin_redshift", "error": str(err)}))
        return {"batchItemFailures": [{"itemIdentifier": r["messageId"]} for r in records]}

    guardados = 0
    if filas:
        try:
            insertar([f for _, f in filas])
            guardados = len(filas)
        except Exception as err:  # noqa: BLE001 — se aísla el mensaje malo
            print(json.dumps({"evento": "error_lote", "error": str(err)[:300]}))
            for mid, f in filas:
                try:
                    insertar([f])
                    guardados += 1
                except Exception as err_fila:  # noqa: BLE001
                    print(json.dumps({"evento": "error_fila", "id": mid, "error": str(err_fila)[:300]}))
                    fallidos.append(mid)

    print(json.dumps({"evento": "lote", "recibidos": len(records), "guardados": guardados,
                      "fallidos": len(fallidos)}))
    return {"batchItemFailures": [{"itemIdentifier": m} for m in fallidos]}
