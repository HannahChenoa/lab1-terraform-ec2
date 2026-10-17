"""
Ayudante para la Redshift Data API (la usan las Lambdas "guardar" y "consulta").

La Data API ejecuta SQL por HTTPS: no hace falta VPC, driver ni conexión abierta.
Es asíncrona: execute_statement devuelve un Id y hay que esperar a que termine.
"""
import os
import time

import boto3

rsd = boto3.client("redshift-data")

DATABASE = os.environ["DATABASE"]
SECRET_ARN = os.environ["SECRET_ARN"]
# Clúster provisionado (CLUSTER_ID) o Redshift Serverless (WORKGROUP): la Data API sirve para ambos
if os.environ.get("CLUSTER_ID"):
    DESTINO = {"ClusterIdentifier": os.environ["CLUSTER_ID"]}
else:
    DESTINO = {"WorkgroupName": os.environ["WORKGROUP"]}


class ErrorRedshift(Exception):
    pass


def _esperar(statement_id: str, timeout_s: float) -> dict:
    limite = time.time() + timeout_s
    pausa = 0.05
    while True:
        d = rsd.describe_statement(Id=statement_id)
        if d["Status"] == "FINISHED":
            return d
        if d["Status"] in ("FAILED", "ABORTED"):
            raise ErrorRedshift(d.get("Error", d["Status"]))
        if time.time() > limite:
            raise ErrorRedshift(f"timeout esperando {statement_id}")
        time.sleep(pausa)
        pausa = min(pausa * 1.5, 0.5)


def ejecutar(sql: str, timeout_s: float = 45) -> dict:
    r = rsd.execute_statement(**DESTINO, Database=DATABASE, SecretArn=SECRET_ARN, Sql=sql)
    return _esperar(r["Id"], timeout_s)


def ejecutar_varias(sentencias: list[str], timeout_s: float = 45) -> dict:
    """Varias sentencias en una sola transacción."""
    r = rsd.batch_execute_statement(**DESTINO, Database=DATABASE, SecretArn=SECRET_ARN, Sqls=sentencias)
    return _esperar(r["Id"], timeout_s)


def consultar(sql: str, timeout_s: float = 25) -> list[dict]:
    """SELECT -> lista de diccionarios {columna: valor}."""
    d = ejecutar(sql, timeout_s)
    if not d.get("HasResultSet"):
        return []
    filas, token = [], None
    while True:
        kw = {"Id": d["Id"]}
        if token:
            kw["NextToken"] = token
        res = rsd.get_statement_result(**kw)
        cols = [c["name"] for c in res["ColumnMetadata"]]
        for registro in res["Records"]:
            filas.append({c: _valor(v) for c, v in zip(cols, registro)})
        token = res.get("NextToken")
        if not token:
            return filas


def _valor(campo: dict):
    if campo.get("isNull"):
        return None
    for tipo in ("stringValue", "longValue", "doubleValue", "booleanValue"):
        if tipo in campo:
            return campo[tipo]
    return None


def texto(v, maximo: int = 256) -> str:
    """Literal SQL seguro para Redshift: NULL o 'texto' con comillas y backslash escapados."""
    if v is None:
        return "NULL"
    s = str(v)[:maximo].replace("\\", "\\\\").replace("'", "''")
    return f"'{s}'"


def entero(v) -> str:
    if v is None or isinstance(v, bool):
        return "NULL"
    return str(int(v))


def booleano(v) -> str:
    return "TRUE" if v else "FALSE"
