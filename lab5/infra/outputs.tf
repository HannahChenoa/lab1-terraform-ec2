# preparar.ps1 vuelca estos valores a sensores/outputs.json y dashboard/.env

output "region" {
  value = var.region
}

output "api_url" {
  description = "URL base de API Gateway (POST /eventos, GET /resumen, GET /db/resumen)"
  value       = aws_api_gateway_stage.v1.invoke_url
}

output "stream_name" {
  value = data.aws_kinesis_stream.sensores.name
}

output "cola_url" {
  value = aws_sqs_queue.eventos.id
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.id
}

output "redshift_cluster" {
  value = aws_redshift_cluster.boda.cluster_identifier
}

output "redshift_database" {
  value = var.db_nombre
}

output "redshift_secret_arn" {
  value = aws_secretsmanager_secret.redshift.arn
}

output "redshift_secret_name" {
  value = aws_secretsmanager_secret.redshift.name
}

output "cloudwatch_dashboard_url" {
  value = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards:name=${aws_cloudwatch_dashboard.flujo.dashboard_name}"
}
