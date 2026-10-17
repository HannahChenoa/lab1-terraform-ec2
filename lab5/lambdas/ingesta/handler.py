"""
[0] Lambda "ingesta":  API Gateway (POST /eventos)  ->  Kinesis

Es la puerta de entrada: la web de RSVP, el bot de WhatsApp, la app del
planner y el escáner de la puerta mandan sus eventos aquí.

Acepta un evento o un lote:
    {"evento_id": ..., ...}
    [{...}, {...}]
    {"eventos": [{...}, {...}]}

Solo hace una validación mínima (que sea JSON y traiga ids) y responde rápido
con 202; la validación completa la hace el procesador más adelante en el flujo.
"""
import json
import os
import time

import boto3

kinesis = boto3.client("kinesis")
STREAM = os.environ["STREAM_NAME"]
MAX_EVENTOS = 500  # máximo de put_records por llamada


def respuesta(status: int, cuerpo: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps(cuerpo, ensure_ascii=False),
    }


def handler(event, context):
    inicio = time.perf_counter()
    try:
        cuerpo = json.loads(event.get("body") or "")
    except ValueError:
        return respuesta(400, {"error": "el body no es JSON"})

    eventos = cuerpo.get("eventos") if isinstance(cuerpo, dict) and "eventos" in cuerpo else cuerpo
    if isinstance(eventos, dict):
        eventos = [eventos]
    if not isinstance(eventos, list) or not eventos:
        return respuesta(400, {"error": "se esperaba un evento o una lista de eventos"})
    if len(eventos) > MAX_EVENTOS:
        return respuesta(413, {"error": f"máximo {MAX_EVENTOS} eventos por request"})

    registros, rechazados = [], 0
    for e in eventos:
        if isinstance(e, dict) and e.get("evento_id") and e.get("invitado_id"):
            registros.append({"Data": json.dumps(e, ensure_ascii=False).encode(),
                              "PartitionKey": str(e["invitado_id"])})
        elif isinstance(e, str):  # texto crudo (p. ej. prueba de registros corruptos)
            registros.append({"Data": e.encode(), "PartitionKey": "crudo"})
        else:
            rechazados += 1

    fallidos = 0
    if registros:
        resp = kinesis.put_records(StreamName=STREAM, Records=registros)
        fallidos = resp["FailedRecordCount"]
        if fallidos:  # reintento único (throttling del shard)
            time.sleep(0.2)
            reintento = [r for r, res in zip(registros, resp["Records"]) if "ErrorCode" in res]
            fallidos = kinesis.put_records(StreamName=STREAM, Records=reintento)["FailedRecordCount"]

    aceptados = len(registros) - fallidos
    return respuesta(202 if aceptados else 503, {
        "aceptados": aceptados,
        "rechazados": rechazados,
        "fallidos_kinesis": fallidos,
        "ingesta_ms": round((time.perf_counter() - inicio) * 1000, 1),
    })
