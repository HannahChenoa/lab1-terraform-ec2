"""
Consulta Redshift desde la terminal con la Redshift Data API (la misma que usan las Lambdas).
Sirve como alternativa a Query Editor v2, que el Learner Lab no deja usar.

    py consultar_redshift.py
    py consultar_redshift.py "SELECT estado, COUNT(*) FROM v_invitados_actual GROUP BY estado"
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import boto3

POR_DEFECTO = [
    ("Tabla columnar 'eventos' (total de filas por tipo)",
     "SELECT tipo, COUNT(*) AS eventos FROM v_eventos GROUP BY tipo ORDER BY eventos DESC"),
    ("Vista v_invitados_actual (primeros 15 invitados)",
     "SELECT invitado_id, nombre, lado, estado, mesa, asiento, menu, restriccion, "
     "CASE WHEN llego THEN 'si' ELSE '' END AS llego FROM v_invitados_actual "
     "ORDER BY mesa NULLS LAST, asiento LIMIT 15"),
]


def outputs():
    infra = Path(__file__).parent / "infra"
    raw = subprocess.run(["terraform", "output", "-json"], cwd=infra, capture_output=True,
                         text=True, shell=os.name == "nt").stdout
    return {k: v["value"] for k, v in json.loads(raw).items()}


def tabla(cols, filas):
    filas = [["" if v is None else str(v) for v in f] for f in filas]
    anchos = [max(len(c), *(len(f[i]) for f in filas)) if filas else len(c) for i, c in enumerate(cols)]
    linea = lambda vals: "  ".join(v.ljust(a) for v, a in zip(vals, anchos))
    print(linea(cols))
    print(linea(["-" * a for a in anchos]))
    for f in filas:
        print(linea(f))


def main():
    os.system("")
    o = outputs()
    try:
        sesion = boto3.Session(profile_name="academy", region_name=o["region"])
    except Exception:
        sesion = boto3.Session(region_name=o["region"])
    rsd = sesion.client("redshift-data")
    consultas = [("Consulta", sys.argv[1])] if len(sys.argv) > 1 else POR_DEFECTO

    print(f"Redshift: clúster {o['redshift_cluster']} / base {o['redshift_database']} (Data API)\n")
    for titulo, sql in consultas:
        inicio = time.perf_counter()
        r = rsd.execute_statement(ClusterIdentifier=o["redshift_cluster"], Database=o["redshift_database"],
                                  SecretArn=o["redshift_secret_arn"], Sql=sql)
        while True:
            d = rsd.describe_statement(Id=r["Id"])
            if d["Status"] in ("FINISHED", "FAILED", "ABORTED"):
                break
            time.sleep(0.3)
        if d["Status"] != "FINISHED":
            sys.exit(f"Error: {d.get('Error')}")
        res = rsd.get_statement_result(Id=r["Id"])
        cols = [c["name"] for c in res["ColumnMetadata"]]
        filas = [[next(iter(c.values())) if not c.get("isNull") else None for c in reg] for reg in res["Records"]]
        print(f"\033[36m=== {titulo} ===\033[0m")
        print(f"\033[90m{sql}\033[0m\n")
        tabla(cols, filas)
        print(f"\n\033[90m{len(filas)} filas en {(time.perf_counter() - inicio) * 1000:.0f} ms\033[0m\n")


if __name__ == "__main__":
    main()
