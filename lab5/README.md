# Lab 5 — Streaming en AWS: API Gateway → Kinesis → Lambda → SQS → Lambda → Redshift Serverless → Grafana

**Enunciado:** desplegar con Terraform un servicio de streaming en AWS que procese datos, los guarde en
una **base de datos columnar** y se consuma con **Grafana**, usando API Gateway, Kinesis/SQS, Lambda,
Redshift Serverless y Grafana, y que soporte múltiples requests sin degradar su rendimiento.

**Caso de uso:** un wedding planner necesita saber en tiempo real cómo va su evento: quién confirmó,
quién canceló, dónde se sienta cada quien, qué va a comer y quién ya llegó. Esos datos son **eventos**
que llegan de distintos lados (la web de RSVP, WhatsApp, el planner acomodando mesas y el escáner de la
puerta el día de la boda).

```
 Web RSVP / WhatsApp / app del planner / escáner QR en la puerta     (simulador.py, carga.py)
                                │  HTTPS
                                ▼
         [0] API Gateway (REST, stage v1, throttling 100 req/s)
              │ POST /eventos                     │ GET /resumen  (CON cache, TTL 60 s)
              ▼                                   │ GET /db/resumen (SIN cache)
         Lambda ingesta                           ▼
              │ put_records                  Lambda consulta ──────────────┐
              ▼                                                            │ Redshift Data API
         [1] Kinesis Data Stream (1 shard)                                 │
              │ trigger (lotes de 100)                                     │
              ▼                                                            │
         [2] Lambda procesador  ── valida, genera alertas ── inválidos → DLQ
              │ send_message_batch                                         │
              ▼                                                            │
         [3] SQS eventos (+ DLQ)  ← amortigua: si Redshift se alenta, aquí esperan
              │ trigger (lotes de 100)                                     │
              ▼                                                            │
         [4] Lambda guardar  ── 1 INSERT multi-fila por lote (Redshift Data API)
              │                                                            │
              ▼                                                            │
         [5] Redshift Serverless (columnar)  ◄─────────────────────────────┘
              │  tabla eventos (SORTKEY ts) + vistas
              ▼
         Grafana (plugin Redshift + CloudWatch)  ·  Dashboard de CloudWatch
```

## Servicios y para qué se usa cada uno

| Servicio | Rol en el flujo |
|---|---|
| **API Gateway (REST)** | Puerta de entrada HTTPS. `POST /eventos` recibe eventos (uno o lote de hasta 500). `GET /resumen` tiene **cache de API Gateway** y `GET /db/resumen` hace la misma consulta sin cache. Throttling a 100 req/s. |
| **Lambda ingesta** | Valida lo mínimo y escribe en Kinesis con `put_records`; responde 202 rápido. |
| **Kinesis Data Streams** | Stream de ingesta continua ("el Kafka de AWS"); desacopla a quien produce de quien procesa. |
| **Lambda procesador** | La dispara Kinesis en lotes. Valida cada evento según su tipo, genera alertas (cancelación de último momento, avisos a catering) y manda los inválidos a la DLQ. |
| **SQS + DLQ** | Cola entre el procesamiento y la base. Si Redshift se alenta, los mensajes esperan; los que fallan 3 veces van a la DLQ. |
| **Lambda guardar** | La dispara SQS con lotes de hasta 100 y hace **un solo INSERT multi-fila** por lote (así se carga una base columnar). Usa la Redshift Data API: sin VPC, sin driver. |
| **Redshift Serverless** | Base de datos **columnar** (8 RPU, tope diario de 16 RPU-h). Tabla de hechos `eventos` + vistas con funciones de ventana. |
| **Lambda consulta** | Ejecuta el resumen del planner en Redshift para `/resumen` y `/db/resumen`. |
| **Grafana** | Dashboard en vivo: métricas de cada servicio (CloudWatch) y el panel del planner (Redshift). |
| **CloudWatch** | Logs (1 día) y dashboard `lab5-boda-flujo`. |

## Modelo de datos (columnar)

- **`eventos`**: tabla de hechos *append-only*, `SORTKEY (ts)`. Nunca se actualiza fila por fila.
- **`v_eventos`**: quita duplicados de SQS (`ROW_NUMBER() OVER (PARTITION BY evento_id)`). Esto da idempotencia.
- **`v_invitados`**: estado actual de cada invitado (último RSVP, último asiento, primera llegada) calculado con funciones de ventana **por la hora del evento**. Así no importa que SQS estándar entregue en desorden.
- **`v_boda_actual`, `v_invitados_actual`, `v_eventos_actual`**: la boda más reciente; cada corrida del simulador es una boda nueva y las pruebas de carga (`carga-*`) se excluyen.

### Eventos

| Tipo | Quién lo genera | Datos |
|---|---|---|
| `invitacion` | Se envía la invitación | nombre, lado (novia / novio) |
| `rsvp` | El invitado responde por web, WhatsApp o llamada | confirmado / cancelado, menú, restricción |
| `asiento` | El planner acomoda las mesas | mesa, silla |
| `checkin` | Escáner en la puerta el día de la boda | método (QR / pulsera NFC) |

## Rendimiento: muchas requests sin degradarse, y cache

`sensores/carga.py` mide desde tu compu contra API Gateway:

1. **Ingesta concurrente:** `POST /eventos` con 1, 5, 10 y 20 clientes simultáneos. Reporta promedio, p50, p95, p99 y req/s. Que la latencia se mantenga parecida mientras el throughput sube demuestra que la arquitectura escala: API Gateway + Lambda escalan solas y Kinesis/SQS absorben la carga antes de Redshift.
2. **Sin cache vs con cache** (como en el lab 4: dos endpoints reales con la misma consulta):
   - `GET /db/resumen` siempre consulta Redshift.
   - `GET /resumen` responde desde la cache de API Gateway durante el TTL. La prueba de que es la cache es que todas las respuestas traen el mismo `generado_en`.
   - Se mide en serie y con 10 clientes concurrentes.

## AWS Managed Grafana en el Learner Lab

Managed Grafana requiere **IAM Identity Center (SSO)** o SAML para iniciar sesión, y un rol IAM propio. El Learner Lab no permite habilitar Identity Center ni crear roles. `probar_servicios.ps1` lo comprueba en tu cuenta y deja la evidencia en pantalla. Por eso se usa **Grafana OSS** (el mismo producto que corre Managed Grafana) en Docker, con el plugin oficial `grafana-redshift-datasource` y CloudWatch, autenticado con las credenciales del Learner Lab.

---

## Qué necesitas

| | |
|---|---|
| AWS Academy Learner Lab | Sesión iniciada y credenciales en `~/.aws/credentials` con el profile `academy` |
| Terraform ≥ 1.5 | `terraform -version` |
| Python 3.9+ | En Windows usa `py` |
| Docker Desktop | Abierto, con "Engine running" |

Las credenciales caducan cada ~4 h. Si sale `ExpiredToken` o `InvalidClientTokenId`, vuelve a pegarlas.

## Pasos

```powershell
cd lab5

# 0) Qué permite la cuenta + que no haya sobras cobrando
.\probar_servicios.ps1
py -m pip install boto3
py verificar_cuenta.py

# 1) Infraestructura (~8-10 min; Redshift Serverless es lo más tardado)
cd infra
terraform init
terraform plan
terraform apply
cd ..

# 2) Config para el simulador, la prueba de carga y Grafana
.\preparar.ps1

# 3) Grafana  ->  http://localhost:3000
cd dashboard
docker compose up -d
cd ..

# 4) La boda (~4 min, 100 invitados, todo entra por API Gateway)
cd sensores
py simulador.py

# 5) Prueba de rendimiento (ingesta concurrente + sin cache vs con cache)
py carga.py
```

Errores a propósito: `py simulador.py --corruptos 0.05 --segundos-por-fase 20` hace que suba el contador ☠️ DLQ.

## Presupuesto del Learner Lab

| Recurso | Configuración | Costo aprox. |
|---|---|---|
| Redshift Serverless | 8 RPU base = máximo, **tope de 16 RPU-h al día** (al pasarlo se desactiva solo) | ~3 USD por hora **mientras ejecuta consultas**; 0 sin uso |
| API Gateway | cache de 0.5 GB, throttling 100 req/s | ~0.02 USD/hora la cache + centavos por requests |
| Kinesis | 1 shard aprovisionado, 24 h de retención | ~0.015 USD/hora |
| Lambda / SQS | máx. 2 Lambdas escribiendo a Redshift | centavos |
| Simulador / carga | topes en el código (200 invitados, 20 req/s; 20 clientes, 100 requests por nivel) | — |

El dashboard de Grafana refresca cada 30 s (no 10 s) porque cada refresco son consultas a Redshift.
**Una sesión de ~1 hora cuesta del orden de 3–4 USD. Al terminar, siempre:**

```powershell
.\destruir.ps1
```

Apaga Grafana, corre `terraform destroy`, confirma que el state quedó en 0 y revisa la cuenta con `verificar_cuenta.py`.

## Estructura

```
lab5/
├── infra/                  Terraform: API Gateway (cache), Kinesis, SQS+DLQ, 4 Lambdas,
│                           Redshift Serverless (+ límite de uso), Secrets Manager, dashboard CloudWatch
├── lambdas/
│   ├── ingesta/            [0] API Gateway → Kinesis
│   ├── procesador/         [2] Kinesis → SQS (valida y genera alertas)
│   ├── guardar/            [4] SQS → Redshift (crea tabla y vistas; INSERT por lotes)
│   └── consulta/           GET /resumen y /db/resumen → Redshift
├── sensores/
│   ├── simulador.py        La boda: invitaciones, RSVP, mesas y check-ins → API Gateway
│   ├── carga.py            Prueba de rendimiento (concurrencia y cache)
│   └── api.py              Cliente HTTP (solo librería estándar)
├── dashboard/              Grafana en Docker (plugin Redshift, datasources y dashboard provisionados)
│   └── generar_dashboard.py  Genera grafana/dashboards/boda.json
├── sql/consultas.sql       Consultas para Query Editor v2 / Grafana Explore
├── probar_servicios.ps1    Qué servicios permite la cuenta (incluye prueba de Managed Grafana)
├── preparar.ps1            Outputs de Terraform → simulador y Grafana
├── destruir.ps1            Borra todo y verifica
└── verificar_cuenta.py     Lista lo que sigue cobrando en la cuenta (cualquier lab)
```

## Decisiones de diseño

- **Redshift Data API en lugar de conexión JDBC:** las Lambdas no necesitan VPC, ENIs ni driver. El despliegue y el destroy son más rápidos y no hay conexiones que agotar.
- **INSERT por lotes y tabla append-only:** en una base columnar los UPDATE fila por fila son caros. Se insertan lotes y el estado se deriva con vistas.
- **SQS antes de Redshift:** Redshift no está hecho para miles de escrituras pequeñas simultáneas. La cola y la concurrencia máxima de 2 Lambdas lo protegen; en un pico los mensajes esperan en lugar de fallar.
- **Cache en API Gateway para las lecturas:** el resumen se pide mucho y cambia poco. Con TTL de 60 s, miles de lecturas cuestan una sola consulta a Redshift.
- **Kinesis con AWS CLI desde Terraform:** el recurso `aws_kinesis_stream` llama a `IncreaseStreamRetentionPeriod`, que el Learner Lab bloquea. Se crea con `terraform_data` + `local-exec` y se borra igual en `destroy`.
