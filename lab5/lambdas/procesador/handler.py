"""
[2] Lambda "procesador":  Kinesis  ->  procesar  ->  SQS

La dispara Kinesis con lotes de hasta 100 eventos de la boda:

  invitacion  se envió la invitación (el invitado queda "pendiente")
  rsvp        el invitado confirmó o canceló (web / WhatsApp / llamada)
  asiento     el planner le asignó mesa y silla
  checkin     el invitado llegó (escáner QR / pulsera NFC en la puerta)

Por cada evento:
  - decodifica (Kinesis entrega base64) y valida según el tipo
  - genera alertas para el planner (cancelaciones, avisos a catering)
  - manda los válidos a SQS y los inválidos directo a la DLQ con el motivo

La Lambda NO guarda estado: las alertas que dependen del estado acumulado
(mesa con sobrecupo, alguien llegó sin confirmar) se calculan con SQL en la base.
"""
import base64
import json
import os
from datetime import datetime, timezone

import boto3

sqs = boto3.client("sqs")
COLA_URL = os.environ["COLA_URL"]
DLQ_URL = os.environ["DLQ_URL"]

TIPOS = {"invitacion", "rsvp", "asiento", "checkin"}
RESPUESTAS = {"confirmado", "cancelado"}
MENUS = {"res", "pollo", "vegetariano", "infantil"}
CANALES = {"web", "whatsapp", "llamada"}
METODOS_CHECKIN = {"qr", "pulsera_nfc", "lista"}
MAX_MESAS, MAX_SILLAS = 50, 12


class Invalido(Exception):
    pass


def _exigir(d: dict, *campos: str) -> None:
    faltan = [c for c in campos if d.get(c) in (None, "")]
    if faltan:
        raise Invalido(f"faltan campos: {faltan}")


def _en(d: dict, campo: str, permitidos: set) -> None:
    if d.get(campo) not in permitidos:
        raise Invalido(f"{campo} inválido: {d.get(campo)!r}")


def procesar_evento(d: dict) -> tuple[dict, list[str]]:
    """Valida y devuelve (detalle, alertas)."""
    tipo = d["tipo"]
    alertas: list[str] = []

    if tipo == "invitacion":
        _exigir(d, "lado")
        detalle = {"lado": d["lado"]}

    elif tipo == "rsvp":
        _en(d, "respuesta", RESPUESTAS)
        _en(d, "canal", CANALES)
        detalle = {"respuesta": d["respuesta"], "canal": d["canal"]}
        if d["respuesta"] == "confirmado":
            _en(d, "menu", MENUS)
            detalle["menu"] = d["menu"]
            if d.get("restriccion"):
                detalle["restriccion"] = d["restriccion"]
                alertas.append(f"avisar a catering: {d['restriccion']}")
        else:
            if d.get("ultimo_momento"):
                alertas.append("cancelación de último momento: liberar su lugar en la mesa")
            else:
                alertas.append("canceló")

    elif tipo == "asiento":
        mesa, silla = d.get("mesa"), d.get("asiento")
        if not isinstance(mesa, int) or not 1 <= mesa <= MAX_MESAS:
            raise Invalido(f"mesa inválida: {mesa!r}")
        if not isinstance(silla, int) or not 1 <= silla <= MAX_SILLAS:
            raise Invalido(f"asiento inválido: {silla!r}")
        detalle = {"mesa": mesa, "asiento": silla}

    else:  # checkin
        _en(d, "metodo", METODOS_CHECKIN)
        detalle = {"metodo": d["metodo"], "puerta": d.get("puerta", "principal")}

    return detalle, alertas


def procesar(registro: dict) -> dict:
    try:
        d = json.loads(base64.b64decode(registro["kinesis"]["data"]))
    except (ValueError, KeyError) as e:
        raise Invalido(f"no es JSON: {e}") from e

    _exigir(d, "evento_id", "boda_id", "invitado_id", "nombre", "tipo", "ts")
    _en(d, "tipo", TIPOS)
    detalle, alertas = procesar_evento(d)

    try:
        ts = datetime.fromisoformat(d["ts"].replace("Z", "+00:00")).timestamp()
    except ValueError as e:
        raise Invalido(f"ts inválido: {d['ts']!r}") from e
    llegada = registro["kinesis"]["approximateArrivalTimestamp"]  # segundos

    return {
        "evento_id": d["evento_id"],
        "boda_id": d["boda_id"],
        "invitado_id": d["invitado_id"],
        "nombre": d["nombre"],
        "tipo": d["tipo"],
        "ts": d["ts"],
        "detalle": detalle,
        "alerta": bool(alertas),
        "motivo_alerta": "; ".join(alertas),
        "latencia_ingesta_ms": max(0, int((llegada - ts) * 1000)),
        "procesado_en": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }


def _enviar(url: str, mensajes: list[dict]) -> None:
    for i in range(0, len(mensajes), 10):  # SQS acepta 10 por llamada
        resp = sqs.send_message_batch(QueueUrl=url, Entries=mensajes[i : i + 10])
        if resp.get("Failed"):
            raise RuntimeError(f"SQS rechazó {len(resp['Failed'])} mensajes: {resp['Failed'][:2]}")


def handler(event, context):
    validos, invalidos = [], []

    for n, registro in enumerate(event["Records"]):
        try:
            e = procesar(registro)
            validos.append({
                "Id": str(n),
                "MessageBody": json.dumps(e, ensure_ascii=False),
                "MessageAttributes": {
                    "tipo": {"DataType": "String", "StringValue": e["tipo"]},
                    "alerta": {"DataType": "String", "StringValue": str(e["alerta"]).lower()},
                },
            })
        except Invalido as err:
            invalidos.append({
                "Id": str(n),
                "MessageBody": json.dumps({
                    "motivo": str(err),
                    "secuencia": registro["kinesis"]["sequenceNumber"],
                    "dato_crudo": registro["kinesis"]["data"],
                }),
            })

    _enviar(COLA_URL, validos)
    if invalidos:
        _enviar(DLQ_URL, invalidos)

    por_tipo: dict[str, int] = {}
    for m in validos:
        t = m["MessageAttributes"]["tipo"]["StringValue"]
        por_tipo[t] = por_tipo.get(t, 0) + 1
    print(json.dumps({"evento": "lote", "recibidos": len(event["Records"]), "a_sqs": len(validos),
                      "a_dlq": len(invalidos), "por_tipo": por_tipo}))
    return {"a_sqs": len(validos), "a_dlq": len(invalidos)}
