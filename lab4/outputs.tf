output "alb_dns_name" {
  description = "DNS público del Application Load Balancer"
  value       = aws_lb.app.dns_name
}

output "alb_url" {
  description = "URL para probar el endpoint (Lambda + RDS + ElastiCache). Úsala también para el load test con wrk2"
  value       = "http://${aws_lb.app.dns_name}"
}

output "health_url" {
  description = "URL de health check"
  value       = "http://${aws_lb.app.dns_name}/health"
}

output "rds_endpoint" {
  description = "Endpoint (host) de la instancia RDS"
  value       = aws_db_instance.lab4.address
}

output "redis_endpoint" {
  description = "Endpoint del nodo de ElastiCache"
  value       = aws_elasticache_cluster.lab4.cache_nodes[0].address
}

output "db_password" {
  description = "Password generado para RDS (sensible). Ver con: terraform output db_password"
  value       = random_password.db_password.result
  sensitive   = true
}

output "lambda_function_name" {
  description = "Nombre de la función Lambda"
  value       = aws_lambda_function.app.function_name
}
