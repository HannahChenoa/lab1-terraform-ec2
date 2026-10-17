"""
Genera imágenes PNG de las métricas del lab directamente desde CloudWatch
(GetMetricWidgetImage), para el reporte. Las guarda en lab5/capturas/.

    py capturas_cloudwatch.py            # últimos 60 minutos
    py capturas_cloudwatch.py 120        # últimos 120 minutos
"""
import json
import sys
from pathlib import Path

import boto3

MIN = int(sys.argv[1]) if len(sys.argv) > 1 else 60
P = "lab5-boda"
API = {"ApiName": f"{P}-api", "Stage": "v1"}
REGION = "us-east-1"

try:
    cw = boto3.Session(profile_name="academy", region_name=REGION).client("cloudwatch")
except Exception:
    cw = boto3.Session(region_name=REGION).client("cloudwatch")


def m(ns, nombre, dims, label, stat="Sum", color=None, eje=None):
    fila = [ns, nombre]
    for k, v in dims.items():
        fila += [k, v]
    extra = {"label": label, "stat": stat}
    if color:
        extra["color"] = color
    if eje:
        extra["yAxis"] = eje
    return fila + [extra]


GRAFICAS = {
    "cw_cache_hits_misses": ("API Gateway: cache hits vs misses (GET /resumen)", [
        m("AWS/ApiGateway", "CacheHitCount", API, "hits (respondió la cache)", color="#2ca02c"),
        m("AWS/ApiGateway", "CacheMissCount", API, "misses (fue a Redshift)", color="#d62728"),
    ], "bar"),
    "cw_latencia_endpoints": ("API Gateway: latencia promedio por endpoint (ms)", [
        m("AWS/ApiGateway", "Latency", {**API, "Resource": "/resumen", "Method": "GET"},
          "/resumen (CON cache)", "Average", "#2ca02c"),
        m("AWS/ApiGateway", "Latency", {**API, "Resource": "/db/resumen", "Method": "GET"},
          "/db/resumen (SIN cache)", "Average", "#d62728"),
    ], "line"),
    "cw_api_requests": ("0 · API Gateway: requests por minuto", [
        m("AWS/ApiGateway", "Count", API, "requests"),
        m("AWS/ApiGateway", "5XXError", API, "errores 5xx", color="#d62728"),
    ], "bar"),
    "cw_kinesis": ("1 · Kinesis: registros que entran por minuto", [
        m("AWS/Kinesis", "IncomingRecords", {"StreamName": f"{P}-stream"}, "registros"),
    ], "bar"),
    "cw_lambdas": ("2/4 · Lambdas: invocaciones por minuto", [
        m("AWS/Lambda", "Invocations", {"FunctionName": f"{P}-{f}"}, f) for f in ("ingesta", "procesador", "guardar", "consulta")
    ], "line"),
    "cw_sqs": ("3 · SQS: mensajes enviados a la cola / DLQ", [
        m("AWS/SQS", "NumberOfMessagesSent", {"QueueName": f"{P}-eventos"}, "enviados a la cola"),
        m("AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": f"{P}-dlq"}, "en DLQ", "Maximum", "#d62728"),
    ], "line"),
    "cw_redshift": ("5 · Redshift: CPU del clúster (%)", [
        m("AWS/Redshift", "CPUUtilization", {"ClusterIdentifier": f"{P}-rs"}, "CPU %", "Average"),
    ], "line"),
}

destino = Path(__file__).parent / "capturas"
destino.mkdir(exist_ok=True)
for archivo, (titulo, metricas, vista) in GRAFICAS.items():
    widget = {
        "title": titulo, "metrics": metricas, "view": "timeSeries", "stacked": False,
        "region": REGION, "period": 60, "start": f"-PT{MIN}M", "end": "P0D",
        "width": 900, "height": 380, "timezone": "-0600",
        "legend": {"position": "bottom"},
    }
    if vista == "bar":
        widget["setPeriodToTimeRange"] = False
    png = cw.get_metric_widget_image(MetricWidget=json.dumps(widget), OutputFormat="png")["MetricWidgetImage"]
    (destino / f"{archivo}.png").write_bytes(png)
    print(f"OK  capturas\\{archivo}.png")
print("\nListo. Avísale a Claude para que las agregue al reporte.")
