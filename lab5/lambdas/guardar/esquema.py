"""
Esquema en Redshift (columnar).

Una sola tabla de hechos `eventos` (append-only): en una base columnar se
inserta en lotes y nunca se actualiza fila por fila. El "estado actual" de cada
invitado se calcula con vistas usando funciones de ventana sobre el historial.

Ventajas de este diseño:
  - Idempotencia: si SQS entrega un evento dos veces, la vista se queda con uno
    solo (ROW_NUMBER por evento_id).
  - Orden: SQS estándar no garantiza el orden; la vista elige el último RSVP o
    asiento por la hora en que pasó (ts), no por la hora en que llegó.
  - Cada corrida del simulador es una boda nueva (boda_id distinto).
"""

TABLA = """
CREATE TABLE IF NOT EXISTS eventos (
    evento_id           VARCHAR(64)  NOT NULL,
    boda_id             VARCHAR(64)  NOT NULL,
    invitado_id         VARCHAR(32)  NOT NULL,
    nombre              VARCHAR(128),
    tipo                VARCHAR(16)  NOT NULL,
    ts                  TIMESTAMP    NOT NULL,
    lado                VARCHAR(16),
    respuesta           VARCHAR(16),
    canal               VARCHAR(16),
    menu                VARCHAR(16),
    restriccion         VARCHAR(64),
    ultimo_momento      BOOLEAN,
    mesa                INTEGER,
    asiento             INTEGER,
    metodo              VARCHAR(16),
    alerta              BOOLEAN,
    motivo_alerta       VARCHAR(256),
    latencia_ingesta_ms INTEGER,
    guardado_en         TIMESTAMP    DEFAULT SYSDATE
)
DISTSTYLE AUTO
SORTKEY (ts)
"""

VISTAS = [
    # 1) Sin duplicados
    """
CREATE OR REPLACE VIEW v_eventos AS
SELECT evento_id, boda_id, invitado_id, nombre, tipo, ts, lado, respuesta, canal, menu,
       restriccion, ultimo_momento, mesa, asiento, metodo, alerta, motivo_alerta,
       latencia_ingesta_ms, guardado_en
FROM (
    SELECT e.*, ROW_NUMBER() OVER (PARTITION BY evento_id ORDER BY guardado_en) AS rn
    FROM eventos e
) d
WHERE rn = 1
""",
    # 2) Estado actual de cada invitado (por boda)
    """
CREATE OR REPLACE VIEW v_invitados AS
WITH base AS (
    SELECT boda_id, invitado_id, MAX(nombre) AS nombre
    FROM v_eventos GROUP BY boda_id, invitado_id
),
inv AS (
    SELECT boda_id, invitado_id, lado FROM (
        SELECT boda_id, invitado_id, lado,
               ROW_NUMBER() OVER (PARTITION BY boda_id, invitado_id ORDER BY ts DESC) AS r
        FROM v_eventos WHERE tipo = 'invitacion') x
    WHERE r = 1
),
rsvp AS (
    SELECT boda_id, invitado_id, respuesta, menu, restriccion, ts AS rsvp_ts FROM (
        SELECT boda_id, invitado_id, respuesta, menu, restriccion, ts,
               ROW_NUMBER() OVER (PARTITION BY boda_id, invitado_id ORDER BY ts DESC) AS r
        FROM v_eventos WHERE tipo = 'rsvp') x
    WHERE r = 1
),
asi AS (
    SELECT boda_id, invitado_id, mesa, asiento FROM (
        SELECT boda_id, invitado_id, mesa, asiento,
               ROW_NUMBER() OVER (PARTITION BY boda_id, invitado_id ORDER BY ts DESC) AS r
        FROM v_eventos WHERE tipo = 'asiento') x
    WHERE r = 1
),
chk AS (
    SELECT boda_id, invitado_id, MIN(ts) AS hora_llegada
    FROM v_eventos WHERE tipo = 'checkin' GROUP BY boda_id, invitado_id
)
SELECT b.boda_id, b.invitado_id, b.nombre, i.lado,
       COALESCE(r.respuesta, 'pendiente') AS estado,
       CASE WHEN r.respuesta = 'confirmado' THEN r.menu END AS menu,
       CASE WHEN r.respuesta = 'confirmado' THEN r.restriccion END AS restriccion,
       a.mesa, a.asiento,
       CASE WHEN c.hora_llegada IS NOT NULL THEN TRUE ELSE FALSE END AS llego,
       c.hora_llegada, r.rsvp_ts
FROM base b
LEFT JOIN inv  i ON i.boda_id = b.boda_id AND i.invitado_id = b.invitado_id
LEFT JOIN rsvp r ON r.boda_id = b.boda_id AND r.invitado_id = b.invitado_id
LEFT JOIN asi  a ON a.boda_id = b.boda_id AND a.invitado_id = b.invitado_id
LEFT JOIN chk  c ON c.boda_id = b.boda_id AND c.invitado_id = b.invitado_id
""",
    # 3) La boda más reciente (las pruebas de carga usan boda_id 'carga-...' y se excluyen)
    """
CREATE OR REPLACE VIEW v_boda_actual AS
SELECT boda_id FROM (
    SELECT boda_id, MAX(ts) AS ultimo
    FROM v_eventos WHERE boda_id NOT LIKE 'carga-%'
    GROUP BY boda_id
    ORDER BY ultimo DESC
    LIMIT 1
) x
""",
    """
CREATE OR REPLACE VIEW v_invitados_actual AS
SELECT v.* FROM v_invitados v JOIN v_boda_actual b ON b.boda_id = v.boda_id
""",
    """
CREATE OR REPLACE VIEW v_eventos_actual AS
SELECT e.* FROM v_eventos e JOIN v_boda_actual b ON b.boda_id = e.boda_id
""",
]

PERMISOS = [
    "GRANT SELECT ON ALL TABLES IN SCHEMA public TO PUBLIC",
]

TODO = [TABLA, *VISTAS, *PERMISOS]
