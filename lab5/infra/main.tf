# =============================================================================
#  Lab 5 — Data flow de una boda (wedding planner)
#
#  Clientes (web RSVP, WhatsApp, planner, escáner QR en la puerta)
#        │  POST /eventos
#        ▼
#  [0] API Gateway (REST) ──► Lambda "ingesta" ──► [1] Kinesis Data Stream
#                                                        │ trigger (lotes de 100)
#                                                        ▼
#                                                  [2] Lambda "procesador"
#                                                        │ valida, genera alertas
#                                                        ▼
#                                                  [3] SQS "eventos" (+ DLQ)
#                                                        │ trigger (lotes de 100)
#                                                        ▼
#                                                  [4] Lambda "guardar" (Redshift Data API)
#                                                        │
#                                                        ▼
#                                                  [5] Amazon Redshift (clúster columnar, 1 nodo)
#                                                        ▲            ▲
#  GET /resumen     (CON cache de API Gateway) ──► Lambda "consulta"  │
#  GET /db/resumen  (SIN cache)                ──► Lambda "consulta"  │
#                                                                 Grafana
# =============================================================================

# Learner Lab no deja crear roles: todo usa LabRole
data "aws_iam_role" "lab" {
  name = "LabRole"
}

# ----------------------------------------------------------------- [1] Kinesis
# El recurso aws_kinesis_stream siempre llama a IncreaseStreamRetentionPeriod al
# crear (aunque sea el default de 24 h) y el Learner Lab lo bloquea con una SCP.
# Por eso el stream se crea con el AWS CLI, que solo usa CreateStream/DeleteStream.
# Sigue siendo parte de Terraform: se crea en apply y se borra en destroy.
resource "terraform_data" "kinesis_stream" {
  input = {
    name    = "${var.proyecto}-stream"
    shards  = var.kinesis_shards
    profile = var.aws_profile
    region  = var.region
  }

  # 1 shard aprovisionado, retención 24 h por defecto: lo más barato
  provisioner "local-exec" {
    command = "aws kinesis create-stream --stream-name ${self.input.name} --shard-count ${self.input.shards} --stream-mode-details StreamMode=PROVISIONED --profile ${self.input.profile} --region ${self.input.region} && aws kinesis wait stream-exists --stream-name ${self.input.name} --profile ${self.input.profile} --region ${self.input.region}"
  }

  provisioner "local-exec" {
    when    = destroy
    command = "aws kinesis delete-stream --stream-name ${self.input.name} --enforce-consumer-deletion --profile ${self.input.profile} --region ${self.input.region}"
  }
}

data "aws_kinesis_stream" "sensores" {
  name = terraform_data.kinesis_stream.output.name
}

# ----------------------------------------------------------------- [3] SQS
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.proyecto}-dlq"
  message_retention_seconds = 345600 # 4 días para revisarlos
}

resource "aws_sqs_queue" "eventos" {
  name                       = "${var.proyecto}-eventos"
  visibility_timeout_seconds = 360 # 6 x timeout de la Lambda guardar
  message_retention_seconds  = 86400
  receive_wait_time_seconds  = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })
}

# ----------------------------------------------------------------- [5] Amazon Redshift (columnar)
resource "random_password" "db" {
  length           = 24
  special          = true
  override_special = "!#%^*-_=+" # Redshift no acepta / @ " ' \ ni espacios
  min_upper        = 2
  min_lower        = 2
  min_numeric      = 2
}

# Redshift Serverless (CreateNamespace) está bloqueado en el Learner Lab, pero Redshift
# clásico sí se permite: se usa un clúster de 1 nodo, también columnar y con la misma Data API.
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_redshift_subnet_group" "boda" {
  name       = "${var.proyecto}-subnets"
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_redshift_cluster" "boda" {
  cluster_identifier  = "${var.proyecto}-rs"
  cluster_type        = "single-node"
  node_type           = var.redshift_node_type
  database_name       = var.db_nombre
  master_username     = var.db_usuario
  master_password     = random_password.db.result

  cluster_subnet_group_name           = aws_redshift_subnet_group.boda.name
  publicly_accessible                 = false # se usa por la Data API (HTTPS), no por red
  skip_final_snapshot                 = true  # destroy sin dejar snapshots que cobren
  automated_snapshot_retention_period = 1
  apply_immediately                   = true
}

# Credenciales del admin para la Redshift Data API (Lambdas y Grafana usan el mismo usuario)
resource "aws_secretsmanager_secret" "redshift" {
  name                    = "${var.proyecto}-redshift-admin"
  recovery_window_in_days = 0 # se borra al instante en destroy, para poder re-desplegar
  tags = {
    RedshiftQueryOwner = "grafana" # el plugin de Grafana lista secretos con este tag
  }
}

resource "aws_secretsmanager_secret_version" "redshift" {
  secret_id = aws_secretsmanager_secret.redshift.id
  secret_string = jsonencode({
    username = var.db_usuario
    password = random_password.db.result
  })
}

# ----------------------------------------------------------------- Lambdas
locals {
  lambdas = {
    ingesta    = { timeout = 10, memoria = 128 }
    procesador = { timeout = 30, memoria = 128 }
    guardar    = { timeout = 60, memoria = 128 }
    consulta   = { timeout = 29, memoria = 128 } # 29 s = límite de API Gateway
  }

  env_redshift = {
    CLUSTER_ID = aws_redshift_cluster.boda.cluster_identifier
    DATABASE   = var.db_nombre
    SECRET_ARN = aws_secretsmanager_secret.redshift.arn
  }

  env_por_lambda = {
    ingesta    = { STREAM_NAME = data.aws_kinesis_stream.sensores.name }
    procesador = { COLA_URL = aws_sqs_queue.eventos.id, DLQ_URL = aws_sqs_queue.dlq.id }
    guardar    = local.env_redshift
    consulta   = local.env_redshift
  }
}

resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = local.lambdas
  name              = "/aws/lambda/${var.proyecto}-${each.key}"
  retention_in_days = 1
}

data "archive_file" "lambda" {
  for_each    = local.lambdas
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/${each.key}"
  output_path = "${path.module}/build/${each.key}.zip"
}

resource "aws_lambda_function" "f" {
  for_each         = local.lambdas
  function_name    = "${var.proyecto}-${each.key}"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.lambda[each.key].output_path
  source_code_hash = data.archive_file.lambda[each.key].output_base64sha256
  timeout          = each.value.timeout
  memory_size      = each.value.memoria

  environment {
    variables = local.env_por_lambda[each.key]
  }

  depends_on = [aws_cloudwatch_log_group.lambda, aws_secretsmanager_secret_version.redshift]
}

# [1] -> [2]  Kinesis dispara al procesador
resource "aws_lambda_event_source_mapping" "kinesis_a_procesador" {
  event_source_arn                   = data.aws_kinesis_stream.sensores.arn
  function_name                      = aws_lambda_function.f["procesador"].arn
  starting_position                  = "LATEST"
  batch_size                         = 100
  maximum_batching_window_in_seconds = 5 # junta registros hasta 5 s -> menos invocaciones
  parallelization_factor             = 1
  maximum_retry_attempts             = 2
  bisect_batch_on_function_error     = true
  maximum_record_age_in_seconds      = 3600

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.dlq.arn
    }
  }
}

# [3] -> [4]  SQS dispara a guardar. Lotes grandes = menos INSERTs = mejor para una BD columnar
resource "aws_lambda_event_source_mapping" "sqs_a_guardar" {
  event_source_arn                   = aws_sqs_queue.eventos.arn
  function_name                      = aws_lambda_function.f["guardar"].arn
  batch_size                         = 100
  maximum_batching_window_in_seconds = 10
  function_response_types            = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = var.lambda_guardar_max_concurrency
  }
}

# ----------------------------------------------------------------- [0] API Gateway (REST + cache)
resource "aws_api_gateway_rest_api" "boda" {
  name        = "${var.proyecto}-api"
  description = "Entrada de eventos de la boda y resumen para el planner"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

# /eventos
resource "aws_api_gateway_resource" "eventos" {
  rest_api_id = aws_api_gateway_rest_api.boda.id
  parent_id   = aws_api_gateway_rest_api.boda.root_resource_id
  path_part   = "eventos"
}

# /resumen  (CON cache)
resource "aws_api_gateway_resource" "resumen" {
  rest_api_id = aws_api_gateway_rest_api.boda.id
  parent_id   = aws_api_gateway_rest_api.boda.root_resource_id
  path_part   = "resumen"
}

# /db/resumen  (SIN cache, misma Lambda y misma query)
resource "aws_api_gateway_resource" "db" {
  rest_api_id = aws_api_gateway_rest_api.boda.id
  parent_id   = aws_api_gateway_rest_api.boda.root_resource_id
  path_part   = "db"
}

resource "aws_api_gateway_resource" "db_resumen" {
  rest_api_id = aws_api_gateway_rest_api.boda.id
  parent_id   = aws_api_gateway_resource.db.id
  path_part   = "resumen"
}

locals {
  rutas = {
    post_eventos   = { recurso = aws_api_gateway_resource.eventos.id, metodo = "POST", lambda = "ingesta" }
    get_resumen    = { recurso = aws_api_gateway_resource.resumen.id, metodo = "GET", lambda = "consulta" }
    get_db_resumen = { recurso = aws_api_gateway_resource.db_resumen.id, metodo = "GET", lambda = "consulta" }
  }
}

resource "aws_api_gateway_method" "m" {
  for_each      = local.rutas
  rest_api_id   = aws_api_gateway_rest_api.boda.id
  resource_id   = each.value.recurso
  http_method   = each.value.metodo
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "i" {
  for_each                = local.rutas
  rest_api_id             = aws_api_gateway_rest_api.boda.id
  resource_id             = each.value.recurso
  http_method             = aws_api_gateway_method.m[each.key].http_method
  type                    = "AWS_PROXY"
  integration_http_method = "POST"
  uri                     = aws_lambda_function.f[each.value.lambda].invoke_arn
}

resource "aws_lambda_permission" "api" {
  for_each      = toset(["ingesta", "consulta"])
  statement_id  = "PermitirApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.f[each.key].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.boda.execution_arn}/*/*"
}

resource "aws_api_gateway_deployment" "boda" {
  rest_api_id = aws_api_gateway_rest_api.boda.id

  triggers = {
    redeploy = sha1(jsonencode([
      [for k, v in aws_api_gateway_method.m : v.id],
      [for k, v in aws_api_gateway_integration.i : v.id],
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "v1" {
  rest_api_id   = aws_api_gateway_rest_api.boda.id
  deployment_id = aws_api_gateway_deployment.boda.id
  stage_name    = "v1"

  # Cache de API Gateway: 0.5 GB es el tamaño más chico (~0.02 USD/hora)
  cache_cluster_enabled = true
  cache_cluster_size    = "0.5"
}

# Todas las rutas: métricas por método + throttling (protege el presupuesto), sin cache
resource "aws_api_gateway_method_settings" "todas" {
  rest_api_id = aws_api_gateway_rest_api.boda.id
  stage_name  = aws_api_gateway_stage.v1.stage_name
  method_path = "*/*"

  settings {
    metrics_enabled        = true
    caching_enabled        = false
    throttling_rate_limit  = var.api_rate_limit
    throttling_burst_limit = var.api_rate_limit * 2
  }
}

# Solo GET /resumen usa la cache
resource "aws_api_gateway_method_settings" "resumen_con_cache" {
  rest_api_id = aws_api_gateway_rest_api.boda.id
  stage_name  = aws_api_gateway_stage.v1.stage_name
  method_path = "resumen/GET"

  settings {
    metrics_enabled        = true
    caching_enabled        = true
    cache_ttl_in_seconds   = var.api_cache_ttl
    cache_data_encrypted   = false
    throttling_rate_limit  = var.api_rate_limit
    throttling_burst_limit = var.api_rate_limit * 2
  }

  depends_on = [aws_api_gateway_method_settings.todas]
}

# ----------------------------------------------------------------- CloudWatch
locals {
  api_dims = ["ApiName", aws_api_gateway_rest_api.boda.name, "Stage", aws_api_gateway_stage.v1.stage_name]
}

resource "aws_cloudwatch_dashboard" "flujo" {
  dashboard_name = "${var.proyecto}-flujo"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 8, height = 6
        properties = {
          title = "0. API Gateway: requests y errores", region = var.region, stat = "Sum", period = 60
          metrics = [
            concat(["AWS/ApiGateway", "Count"], local.api_dims),
            concat(["AWS/ApiGateway", "4XXError"], local.api_dims),
            concat(["AWS/ApiGateway", "5XXError"], local.api_dims),
          ]
        }
      },
      {
        type = "metric", x = 8, y = 0, width = 8, height = 6
        properties = {
          title = "0. API Gateway: cache hits vs misses", region = var.region, stat = "Sum", period = 60
          metrics = [
            concat(["AWS/ApiGateway", "CacheHitCount"], local.api_dims),
            concat(["AWS/ApiGateway", "CacheMissCount"], local.api_dims),
          ]
        }
      },
      {
        type = "metric", x = 16, y = 0, width = 8, height = 6
        properties = {
          title = "1. Kinesis: registros que entran", region = var.region, stat = "Sum", period = 60
          metrics = [
            ["AWS/Kinesis", "IncomingRecords", "StreamName", data.aws_kinesis_stream.sensores.name],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 8, height = 6
        properties = {
          title = "2/4. Lambdas: invocaciones", region = var.region, stat = "Sum", period = 60
          metrics = [for k in keys(local.lambdas) : ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.f[k].function_name, { label = k }]]
        }
      },
      {
        type = "metric", x = 8, y = 6, width = 8, height = 6
        properties = {
          title = "3. SQS: enviados / en cola / DLQ", region = var.region, period = 60
          metrics = [
            ["AWS/SQS", "NumberOfMessagesSent", "QueueName", aws_sqs_queue.eventos.name, { stat = "Sum" }],
            [".", "ApproximateNumberOfMessagesVisible", ".", ".", { stat = "Maximum" }],
            [".", "ApproximateNumberOfMessagesVisible", ".", aws_sqs_queue.dlq.name, { stat = "Maximum", label = "DLQ" }],
          ]
        }
      },
      {
        type = "metric", x = 16, y = 6, width = 8, height = 6
        properties = {
          title = "5. Redshift: CPU y conexiones", region = var.region, stat = "Average", period = 60
          metrics = [
            ["AWS/Redshift", "CPUUtilization", "ClusterIdentifier", aws_redshift_cluster.boda.cluster_identifier],
            [".", "DatabaseConnections", ".", ".", { yAxis = "right" }],
          ]
        }
      },
    ]
  })
}
