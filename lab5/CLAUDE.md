# Lab 5 (DSE, ITESO) — contexto para Claude Code

Proyecto de Hannah para la materia DSE (Diseño de Sistemas Escalables). Lee `README.md` para el detalle.

## Enunciado oficial (Canvas)
"Deploy a streaming AWS service that process data and save it in a columnar DB and consume it with Grafana."
Con Terraform: **API Gateway, Kinesis/SQS, Kafka/Lambda, Redshift Serverless y AWS Managed Grafana**.
Debe aguantar múltiples requests sin degradarse. Entregables:
1. Repo de GitHub con todo el código (monorepo https://github.com/HannahChenoa/lab1-terraform-ec2, carpeta `lab5/`).
2. PDF con capturas: servicios en la consola de AWS, despliegue de Terraform y métricas en la terminal
   **sin cache vs con cache**; el correo de estudiante visible; URL del repo.
3. Nombre del PDF: `Lab5_706413.pdf`. Entrega: domingo 18 oct 2026, 23:30.

## Arquitectura actual (versión del 17 oct)
API Gateway REST (`POST /eventos` → Lambda ingesta → Kinesis; `GET /resumen` CON cache 0.5 GB TTL 60 s y
`GET /db/resumen` SIN cache → Lambda consulta → Redshift) → Kinesis → Lambda procesador → SQS (+DLQ) →
Lambda guardar → **Redshift Serverless** (Data API, sin VPC). Grafana OSS en Docker con plugin
`grafana-redshift-datasource` (managed secret) + CloudWatch.
- Caso de uso: wedding planner. Eventos invitacion / rsvp / asiento / checkin.
- Redshift: tabla append-only `eventos` (SORTKEY ts) + vistas `v_eventos` (dedupe por evento_id),
  `v_invitados` (estado actual con ROW_NUMBER por ts), `v_boda_actual`, `v_invitados_actual`, `v_eventos_actual`.
  Cada corrida del simulador es una boda nueva (boda_id con HHMM); las pruebas de carga usan `carga-*` y se excluyen.
- `sensores/carga.py`: ingesta con 1/5/10/20 clientes (p50/p95/p99, req/s) + sin cache vs con cache (serie y 10 concurrentes).
- **Managed Grafana**: casi seguro bloqueado (requiere IAM Identity Center / crear roles). `probar_servicios.ps1`
  lo intenta y da la evidencia para la sección "Problemas encontrados" del reporte.

## Historial de decisiones
- Versión anterior (13 oct) usaba RDS PostgreSQL y no tenía API Gateway; se cambió el 17 oct porque el
  enunciado pide BD columnar (Redshift Serverless) y API Gateway. Hannah no quiere DynamoDB.
- Se descartó la versión de frecuencia cardiaca/pasos: no tenía sentido para un wedding planner.

## Restricciones del AWS Academy Learner Lab
- No se pueden crear roles IAM: todo usa **LabRole**.
- Profile **`academy`**, región **us-east-1**, state de Terraform **local** (esta cuenta de Learner Lab es distinta
  a la de los labs 1-4 y no tiene el bucket `hannah.puente`; el backend S3 está comentado en `providers.tf`).
- `aws_kinesis_stream` falla (SCP bloquea IncreaseStreamRetentionPeriod): Kinesis se crea con AWS CLI vía
  `terraform_data` + `local-exec` y se borra en destroy.
- Las credenciales caducan cada ~4 h. Nunca pedir ni escribir credenciales en archivos del proyecto.

## Presupuesto: prioridad alta (ya se le acabó el budget en otro lab)
- Redshift Serverless 8 RPU (base = max) ≈ 3 USD/h mientras consulta; usage limit diario 16 RPU-h con deactivate.
- API Gateway cache 0.5 GB ≈ 0.02 USD/h; throttling 100 req/s. Kinesis 1 shard. Lambda guardar max 2.
- Grafana refresca cada 30 s. Topes en simulador y carga.py.
- Al terminar siempre: `.\destruir.ps1` (docker down + terraform destroy + `verificar_cuenta.py`).

## Entorno de Hannah (Windows + VS Code + PowerShell 5)
- Usar **`py`** y **`py -m pip`** (Python 3.9). `python`/`python3` fallan por el alias de la Microsoft Store.
- Los .ps1 van en UTF-8 **con BOM** (PowerShell 5 rompe los acentos sin BOM).

## Estado (17 oct 2026)
- [x] Código de la versión Redshift + API Gateway escrito y probado localmente (moto + PostgreSQL como
      sustituto de Redshift para el SQL; 17 consultas de Grafana OK; idempotencia y desorden OK).
- [ ] Primer `terraform apply` de esta versión contra AWS (Redshift Serverless y API Gateway cache nunca probados ahí).
- [ ] Capturas, `py carga.py`, reporte `Lab5_706413` (formato del Lab4_706413: portada ITESO, Objetivo,
      Arquitectura, Componentes, Proceso de implementación, Problemas encontrados, Evidencia, Prueba de
      rendimiento, Conclusiones, GitHub), push a GitHub y `.\destruir.ps1`.

## Cómo ayudar
- Responder en español, paso a paso y con comandos de PowerShell.
- Antes de crear recursos nuevos en AWS, avisar el costo aproximado y si se borran con `terraform destroy`.
- No borrar recursos de la cuenta sin que Hannah lo confirme.
