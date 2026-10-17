-- Consultas para el wedding planner en Redshift Serverless
-- (Query Editor v2 de la consola de AWS, o el Explore de Grafana con el datasource "Redshift boda")

-- La tabla columnar y las vistas
SELECT * FROM eventos ORDER BY ts DESC LIMIT 20;
SELECT * FROM v_invitados_actual ORDER BY mesa NULLS LAST, asiento;
SELECT * FROM v_boda_actual;

-- Resumen de RSVP
SELECT estado, COUNT(*) FROM v_invitados_actual GROUP BY estado ORDER BY 2 DESC;

-- Lista para el banquete: platillos y restricciones de los confirmados
SELECT menu, COUNT(*) AS platos FROM v_invitados_actual WHERE estado = 'confirmado' GROUP BY menu ORDER BY 2 DESC;
SELECT nombre, mesa, menu, restriccion FROM v_invitados_actual
WHERE estado = 'confirmado' AND restriccion IS NOT NULL ORDER BY mesa;

-- Ocupación por mesa (cupo 10) y mesas con sobrecupo
SELECT mesa, COUNT(*) AS personas FROM v_invitados_actual
WHERE estado = 'confirmado' AND mesa IS NOT NULL GROUP BY mesa ORDER BY mesa;
SELECT mesa, COUNT(*) AS personas FROM v_invitados_actual
WHERE estado = 'confirmado' AND mesa IS NOT NULL GROUP BY mesa HAVING COUNT(*) > 10;

-- A quién hay que perseguir: no han contestado
SELECT nombre, lado FROM v_invitados_actual WHERE estado = 'pendiente' ORDER BY lado, nombre;

-- Día de la boda: asistencia y colados
SELECT COUNT(CASE WHEN llego THEN 1 END) AS llegaron,
       COUNT(CASE WHEN estado = 'confirmado' THEN 1 END) AS confirmados,
       ROUND(100.0 * COUNT(CASE WHEN llego AND estado = 'confirmado' THEN 1 END)
             / NULLIF(COUNT(CASE WHEN estado = 'confirmado' THEN 1 END), 0), 1) AS pct_asistencia
FROM v_invitados_actual;
SELECT nombre, estado, hora_llegada FROM v_invitados_actual WHERE llego AND estado <> 'confirmado';

-- Historial de un invitado: cada evento que pasó por el flujo
SELECT ts, tipo, respuesta, menu, mesa, metodo, motivo_alerta
FROM v_eventos_actual WHERE invitado_id = 'inv-001' ORDER BY ts;

-- Canal por el que confirman (web / whatsapp / llamada)
SELECT canal, COUNT(*) FROM v_eventos_actual WHERE tipo = 'rsvp' GROUP BY canal ORDER BY 2 DESC;

-- Analítica entre bodas (aquí brilla una base columnar: lee pocas columnas de muchas filas)
SELECT boda_id, COUNT(*) AS eventos, COUNT(DISTINCT invitado_id) AS invitados,
       MIN(ts) AS inicio, MAX(ts) AS fin
FROM v_eventos GROUP BY boda_id ORDER BY inicio DESC;

-- Latencia del flujo completo: API Gateway -> Kinesis -> Lambda -> SQS -> Lambda -> Redshift
SELECT ROUND(AVG(EXTRACT(EPOCH FROM guardado_en) - EXTRACT(EPOCH FROM ts)), 2) AS seg_promedio,
       ROUND(MAX(EXTRACT(EPOCH FROM guardado_en) - EXTRACT(EPOCH FROM ts)), 2) AS seg_max,
       ROUND(AVG(latencia_ingesta_ms)) AS ms_hasta_kinesis
FROM v_eventos_actual;

-- Idempotencia: la tabla puede tener reentregas de SQS, la vista no
SELECT (SELECT COUNT(*) FROM eventos) AS filas_tabla, (SELECT COUNT(*) FROM v_eventos) AS eventos_unicos;
