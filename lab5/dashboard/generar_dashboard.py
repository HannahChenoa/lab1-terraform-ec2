"""
Genera grafana/dashboards/boda.json (el dashboard del lab).

    py generar_dashboard.py

Fuentes:
  - Amazon Redshift (plugin grafana-redshift-datasource): tablas/vistas de la boda
  - CloudWatch: métricas de cada servicio del flujo
"""
import json
from pathlib import Path

PREFIJO = "lab5-boda"
API = f"{PREFIJO}-api"
STAGE = "v1"

RS = {"type": "grafana-redshift-datasource", "uid": "rs"}
CW = {"type": "cloudwatch", "uid": "cw"}
_id = [0]


def nid():
    _id[0] += 1
    return _id[0]


def bucket(col, seg):
    """Agrupa un TIMESTAMP en cubetas de `seg` segundos (Redshift y PostgreSQL)."""
    return (f"TIMESTAMP 'epoch' + FLOOR(EXTRACT(EPOCH FROM {col}) / {seg}) * {seg} "
            f"* INTERVAL '1 second'")


# ----------------------------------------------------------------- targets
def cw(ns, metric, dims, stat="Sum", label=None, ref="A"):
    return {"refId": ref, "datasource": CW, "namespace": ns, "metricName": metric, "dimensions": dims,
            "statistic": stat, "period": "60", "region": "default", "matchExact": True,
            "metricQueryType": 0, "metricEditorMode": 0, "queryMode": "Metrics", "id": "",
            "expression": "", "label": label or metric}


def rs(q, serie=False, ref="A"):
    return {"refId": ref, "datasource": RS, "rawSQL": " ".join(q.split()),
            "format": 0 if serie else 1, "fillMode": {"mode": 0}}


# ----------------------------------------------------------------- paneles
def panel(tipo, titulo, x, y, w, h, targets, desc="", **extra):
    p = {"id": nid(), "type": tipo, "title": titulo, "description": desc,
         "gridPos": {"x": x, "y": y, "w": w, "h": h}, "targets": targets,
         "datasource": targets[0]["datasource"]}
    p.update(extra)
    return p


def fila(titulo, y):
    return {"id": nid(), "type": "row", "title": titulo, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def stat_cfg(unit="none", decimals=0, pasos=None):
    return {
        "fieldConfig": {"defaults": {
            "unit": unit, "decimals": decimals, "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute", "steps": pasos or [{"color": "text", "value": None}]}},
            "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "colorMode": "value", "graphMode": "none", "textMode": "value",
                    "justifyMode": "center"},
    }


def ts_cfg(unit="short", draw="line", stack=False, nombre_por_etiqueta=False):
    defaults = {"unit": unit, "color": {"mode": "palette-classic"},
                "custom": {"drawStyle": draw, "lineWidth": 2, "fillOpacity": 20, "showPoints": "never",
                           "spanNulls": True, "stacking": {"mode": "normal" if stack else "none"}}}
    if nombre_por_etiqueta:
        defaults["displayName"] = "${__field.labels.metric}"
    return {"fieldConfig": {"defaults": defaults, "overrides": []},
            "options": {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                        "tooltip": {"mode": "multi", "sort": "desc"}}}


def color_fijo(nombre, color):
    return {"matcher": {"id": "byName", "options": nombre},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}]}


panels = []
API_DIMS = {"ApiName": API, "Stage": STAGE}

# ================================================================= fila 1: el flujo
panels.append(fila("① Data flow: API Gateway → Kinesis → Lambda → SQS → Lambda → Redshift  "
                   "(CloudWatch, 1–3 min de retraso)", 0))
y = 1
panels += [
    panel("timeseries", "0 · API Gateway: requests", 0, y, 4, 7,
          [cw("AWS/ApiGateway", "Count", API_DIMS, label="requests/min"),
           cw("AWS/ApiGateway", "5XXError", API_DIMS, label="errores 5xx", ref="B")],
          "Todo lo que entra por POST /eventos y GET /resumen", **ts_cfg(draw="bars")),
    panel("timeseries", "1 · Kinesis: registros", 4, y, 4, 7,
          [cw("AWS/Kinesis", "IncomingRecords", {"StreamName": f"{PREFIJO}-stream"}, label="registros/min")],
          **ts_cfg(draw="bars")),
    panel("timeseries", "2 · Lambda procesador", 8, y, 4, 7,
          [cw("AWS/Lambda", "Invocations", {"FunctionName": f"{PREFIJO}-procesador"}, label="invocaciones"),
           cw("AWS/Lambda", "Errors", {"FunctionName": f"{PREFIJO}-procesador"}, label="errores", ref="B")],
          "Kinesis la dispara con lotes de hasta 100 registros", **ts_cfg()),
    panel("timeseries", "3 · SQS: entran / esperan", 12, y, 4, 7,
          [cw("AWS/SQS", "NumberOfMessagesSent", {"QueueName": f"{PREFIJO}-eventos"}, label="a la cola"),
           cw("AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": f"{PREFIJO}-eventos"},
              stat="Maximum", label="esperando", ref="B")], **ts_cfg()),
    panel("timeseries", "4 · Lambda guardar", 16, y, 4, 7,
          [cw("AWS/Lambda", "Invocations", {"FunctionName": f"{PREFIJO}-guardar"}, label="invocaciones"),
           cw("AWS/Lambda", "Errors", {"FunctionName": f"{PREFIJO}-guardar"}, label="errores", ref="B")],
          "SQS la dispara con lotes de hasta 100; un INSERT multi-fila por lote", **ts_cfg()),
    panel("stat", "☠️ DLQ", 20, y, 4, 7,
          [cw("AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": f"{PREFIJO}-dlq"},
              stat="Maximum", label="mensajes en DLQ")],
          "Eventos inválidos o que fallaron 3 veces",
          **stat_cfg(pasos=[{"color": "green", "value": None}, {"color": "red", "value": 1}])),
]
y += 7
panels += [
    panel("timeseries", "⚡ Cache de API Gateway: hits vs misses", 0, y, 6, 7,
          [cw("AWS/ApiGateway", "CacheHitCount", API_DIMS, label="hits (respondió la cache)"),
           cw("AWS/ApiGateway", "CacheMissCount", API_DIMS, label="misses (fue a Redshift)", ref="B")],
          "Solo GET /resumen tiene cache", **ts_cfg(draw="bars")),
    panel("timeseries", "Latencia API: /resumen (cache) vs /db/resumen (sin cache)", 6, y, 6, 7,
          [cw("AWS/ApiGateway", "Latency", {**API_DIMS, "Method": "GET", "Resource": "/resumen"},
              stat="Average", label="/resumen (con cache)"),
           cw("AWS/ApiGateway", "Latency", {**API_DIMS, "Method": "GET", "Resource": "/db/resumen"},
              stat="Average", label="/db/resumen (sin cache)", ref="B")],
          "Misma consulta a Redshift; la diferencia es la cache", **ts_cfg(unit="ms")),
    panel("timeseries", "5 · Redshift: CPU del clúster", 12, y, 6, 7,
          [cw("AWS/Redshift", "CPUUtilization", {"ClusterIdentifier": f"{PREFIJO}-rs"},
              stat="Average", label="CPU %")],
          "Clúster de 1 nodo; la cache de API Gateway evita consultas repetidas", **ts_cfg(unit="percent")),
    panel("stat", "Eventos en Redshift", 18, y, 3, 7,
          [rs("SELECT COUNT(*) AS eventos FROM v_eventos")],
          "Total en la tabla columnar (todas las bodas y pruebas)", **stat_cfg()),
    panel("stat", "Latencia evento → Redshift", 21, y, 3, 7,
          [rs("""SELECT AVG(EXTRACT(EPOCH FROM guardado_en) - EXTRACT(EPOCH FROM ts)) AS segundos
                 FROM v_eventos_actual""")],
          "Promedio desde que se genera el evento hasta que queda guardado",
          **stat_cfg(unit="s", decimals=1, pasos=[{"color": "green", "value": None},
                                                  {"color": "orange", "value": 30}, {"color": "red", "value": 90}])),
]

# ================================================================= fila 2: planner
y += 7
panels.append(fila("② Panel del wedding planner (Redshift: vistas sobre la tabla columnar eventos)", y))
y += 1


def cuenta(cond):
    return f"SELECT COUNT(CASE WHEN {cond} THEN 1 END) AS n FROM v_invitados_actual"


kpis = [
    ("Invitados", "SELECT COUNT(*) AS n FROM v_invitados_actual", "text"),
    ("✅ Confirmados", cuenta("estado = 'confirmado'"), "green"),
    ("❌ Cancelados", cuenta("estado = 'cancelado'"), "red"),
    ("⏳ Sin responder", cuenta("estado = 'pendiente'"), "orange"),
    ("🪑 Confirmados sin mesa", cuenta("estado = 'confirmado' AND mesa IS NULL"), "orange"),
    ("🚪 Ya llegaron", cuenta("llego"), "blue"),
]
for i, (t, q, color) in enumerate(kpis):
    panels.append(panel("stat", t, i * 4, y, 4, 4, [rs(q)],
                        **stat_cfg(pasos=[{"color": color, "value": None}])))
y += 4

panels += [
    panel("piechart", "RSVP: ¿quién viene?", 0, y, 7, 9,
          [rs("SELECT estado, COUNT(*) AS invitados FROM v_invitados_actual GROUP BY estado ORDER BY invitados DESC")],
          options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True},
                   "pieType": "donut", "displayLabels": [],
                   "legend": {"displayMode": "table", "placement": "right", "showLegend": True,
                              "values": ["value", "percent"]}},
          fieldConfig={"defaults": {"color": {"mode": "palette-classic"}},
                       "overrides": [color_fijo("confirmado", "green"), color_fijo("cancelado", "red"),
                                     color_fijo("pendiente", "orange")]}),
    panel("barchart", "🍽️ Platillos para el catering (confirmados)", 7, y, 7, 9,
          [rs("""SELECT menu AS platillo, COUNT(*) AS platos FROM v_invitados_actual
                 WHERE estado = 'confirmado' AND menu IS NOT NULL GROUP BY menu ORDER BY platos DESC""")],
          options={"orientation": "horizontal", "showValue": "always", "legend": {"showLegend": False},
                   "xTickLabelRotation": 0},
          fieldConfig={"defaults": {"color": {"mode": "fixed", "fixedColor": "purple"}}, "overrides": []}),
    panel("bargauge", "Ocupación por mesa (cupo 10)", 14, y, 10, 9,
          [rs("""SELECT 'Mesa ' || LPAD(CAST(mesa AS VARCHAR), 2, '0') AS etiqueta, COUNT(*) AS personas
                 FROM v_invitados_actual WHERE estado = 'confirmado' AND mesa IS NOT NULL
                 GROUP BY mesa ORDER BY mesa""")],
          "Rojo = sobrecupo. Solo cuenta confirmados: una cancelación libera el lugar",
          options={"orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True,
                   "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True},
                   "valueMode": "color", "namePlacement": "left"},
          fieldConfig={"defaults": {"min": 0, "max": 12, "color": {"mode": "thresholds"},
                                    "thresholds": {"mode": "absolute", "steps": [
                                        {"color": "green", "value": None}, {"color": "orange", "value": 10},
                                        {"color": "red", "value": 11}]}}, "overrides": []}),
]
y += 9

panels += [
    panel("timeseries", "Eventos guardados por tipo (cada 30 s)", 0, y, 12, 8,
          [rs(f"""SELECT {bucket('ts', 30)} AS time, tipo AS metric, COUNT(*) AS value
                  FROM v_eventos_actual WHERE $__timeFilter(ts) GROUP BY 1, 2 ORDER BY 1""", serie=True)],
          "invitacion → rsvp → asiento → checkin: así avanza la boda",
          **ts_cfg(draw="bars", stack=True, nombre_por_etiqueta=True)),
    panel("timeseries", "🚪 Llegadas acumuladas vs. confirmados", 12, y, 12, 8,
          [rs(f"""SELECT t AS time, SUM(n) OVER (ORDER BY t ROWS UNBOUNDED PRECEDING) AS llegaron
                  FROM (SELECT {bucket('hora_llegada', 15)} AS t, COUNT(*) AS n FROM v_invitados_actual
                        WHERE llego AND $__timeFilter(hora_llegada) GROUP BY 1) x
                  ORDER BY 1""", serie=True),
           rs("""SELECT CAST($__timeFrom() AS TIMESTAMP) AS time, COUNT(CASE WHEN estado = 'confirmado' THEN 1 END) AS confirmados
                 FROM v_invitados_actual
                 UNION ALL
                 SELECT CAST($__timeTo() AS TIMESTAMP), COUNT(CASE WHEN estado = 'confirmado' THEN 1 END)
                 FROM v_invitados_actual ORDER BY 1""", serie=True, ref="B")],
          "Escaneos en la puerta (QR / pulsera) contra el total que confirmó", **ts_cfg()),
]
y += 8

panels += [
    panel("table", "🚨 Alertas para el planner", 0, y, 10, 11,
          [rs("""SELECT hora, quien, alerta FROM (
                   SELECT ts AS hora, invitado_id || ' · ' || COALESCE(nombre, '') AS quien, motivo_alerta AS alerta
                   FROM v_eventos_actual WHERE alerta AND motivo_alerta <> 'canceló'
                   UNION ALL
                   SELECT hora_llegada, invitado_id || ' · ' || nombre,
                          'llegó sin estar confirmado (' || estado || ')'
                   FROM v_invitados_actual WHERE llego AND estado <> 'confirmado'
                   UNION ALL
                   SELECT MAX(rsvp_ts), 'Mesa ' || CAST(mesa AS VARCHAR),
                          'sobrecupo: ' || CAST(COUNT(*) AS VARCHAR) || ' personas para 10 lugares'
                   FROM v_invitados_actual WHERE estado = 'confirmado' AND mesa IS NOT NULL
                   GROUP BY mesa HAVING COUNT(*) > 10
                 ) a ORDER BY hora DESC LIMIT 40""")],
          "Cancelaciones y catering vienen del procesador; colados y sobrecupo se calculan con SQL",
          options={"showHeader": True, "cellHeight": "sm"}),
    panel("table", "📋 Lista de invitados (vista v_invitados_actual)", 10, y, 14, 11,
          [rs("""SELECT nombre, lado, estado, mesa, asiento, menu, restriccion,
                        CASE WHEN llego THEN '✅' ELSE '' END AS llego, hora_llegada
                 FROM v_invitados_actual ORDER BY mesa NULLS LAST, asiento, nombre""")],
          "Estado actual calculado con funciones de ventana sobre la tabla de eventos",
          options={"showHeader": True, "cellHeight": "sm"},
          fieldConfig={"defaults": {}, "overrides": [
              {"matcher": {"id": "byName", "options": "estado"},
               "properties": [{"id": "custom.cellOptions", "value": {"type": "color-text"}},
                              {"id": "mappings", "value": [{"type": "value", "options": {
                                  "confirmado": {"color": "green", "index": 0},
                                  "cancelado": {"color": "red", "index": 1},
                                  "pendiente": {"color": "orange", "index": 2}}}]}]}]}),
]
y += 11

panels.append(
    panel("table", "📡 El stream en vivo: últimos eventos en Redshift (tabla eventos)", 0, y, 24, 8,
          [rs("""SELECT ts AS hora, tipo, nombre, respuesta, menu, restriccion, mesa, asiento, metodo,
                        ROUND(EXTRACT(EPOCH FROM guardado_en) - EXTRACT(EPOCH FROM ts), 1) AS seg_hasta_redshift
                 FROM v_eventos_actual ORDER BY ts DESC LIMIT 15""")],
          "seg_hasta_redshift = desde que se generó el evento hasta que quedó guardado",
          options={"showHeader": True, "cellHeight": "sm"}))

dashboard = {
    "uid": "boda-en-vivo",
    "title": "💍 Boda en vivo — Panel del planner",
    "tags": ["lab5", "kinesis", "sqs", "lambda", "redshift", "api-gateway"],
    "timezone": "browser",
    "editable": True,
    "refresh": "30s",  # Redshift cobra mientras consulta: 30 s en lugar de 10 s
    "time": {"from": "now-15m", "to": "now"},
    "schemaVersion": 39,
    "panels": panels,
}

if __name__ == "__main__":
    destino = Path(__file__).parent / "grafana" / "dashboards" / "boda.json"
    destino.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(panels)} paneles -> {destino}")
