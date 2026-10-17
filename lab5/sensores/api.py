"""Cliente HTTP mínimo para API Gateway (solo librería estándar, sin dependencias)."""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def url_base() -> str:
    cfg = Path(__file__).with_name("outputs.json")
    if not cfg.exists():
        sys.exit("No existe sensores/outputs.json. Corre primero .\\preparar.ps1")
    return json.loads(cfg.read_text(encoding="utf-8-sig"))["api_url"].rstrip("/")


def _pedir(req: urllib.request.Request, timeout: float):
    inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, TimeoutError) as e:
        return 0, {"error": str(e)}, (time.perf_counter() - inicio) * 1000
    ms = (time.perf_counter() - inicio) * 1000
    try:
        cuerpo = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        cuerpo = {"raw": raw[:200].decode("utf-8", "replace")}
    return status, cuerpo, ms


def post(url: str, datos, timeout: float = 15):
    """-> (status, cuerpo_json, ms)"""
    req = urllib.request.Request(url, data=json.dumps(datos, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    return _pedir(req, timeout)


def get(url: str, timeout: float = 30):
    """-> (status, cuerpo_json, ms)"""
    return _pedir(urllib.request.Request(url, method="GET"), timeout)
