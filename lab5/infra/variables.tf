variable "region" {
  type    = string
  default = "us-east-1"
}

variable "aws_profile" {
  type    = string
  default = "academy"
}

variable "proyecto" {
  description = "Prefijo de todos los recursos (el dashboard de Grafana asume este valor)"
  type        = string
  default     = "lab5-boda"
}

variable "db_nombre" {
  type    = string
  default = "boda"
}

variable "db_usuario" {
  type    = string
  default = "planner"
}

# ---------- Límites de costo / carga (Learner Lab tiene presupuesto) ----------

variable "kinesis_shards" {
  description = "1 shard aguanta 1,000 registros/s de entrada; para la demo sobra"
  type        = number
  default     = 1
}

variable "redshift_node_type" {
  description = "Tipo de nodo del clúster de Redshift (1 nodo). Ver los permitidos con describe-orderable-cluster-options"
  type        = string
  default     = "ra3.large"
}

variable "api_cache_ttl" {
  description = "Segundos que API Gateway guarda en cache la respuesta de GET /resumen"
  type        = number
  default     = 60
}

variable "api_rate_limit" {
  description = "Requests/s máximos que acepta API Gateway (protege el presupuesto)"
  type        = number
  default     = 100
}

variable "lambda_guardar_max_concurrency" {
  description = "Máximo de Lambdas escribiendo a Redshift en paralelo (2 es el mínimo que permite AWS)"
  type        = number
  default     = 2
}
