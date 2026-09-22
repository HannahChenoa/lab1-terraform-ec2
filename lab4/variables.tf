variable "aws_profile" {
  description = "Nombre del profile de AWS (definido en ~/.aws/credentials) a usar"
  type        = string
  default     = "academy"
}

variable "aws_region" {
  description = "Región de AWS donde se despliega la infraestructura"
  type        = string
  default     = "us-east-1"
}

variable "lambda_role_name" {
  description = "Nombre del IAM role EXISTENTE que usará la Lambda. En AWS Academy no se pueden crear roles nuevos (iam:CreateRole está denegado), así que reutilizamos el LabRole que ya trae la cuenta."
  type        = string
  default     = "LabRole"
}

variable "db_name" {
  description = "Nombre de la base de datos MySQL"
  type        = string
  default     = "lab4db"
}

variable "db_username" {
  description = "Usuario administrador de RDS"
  type        = string
  default     = "lab4admin"
}

variable "db_instance_class" {
  description = "Clase de instancia de RDS (free tier)"
  type        = string
  default     = "db.t3.micro"
}

variable "cache_node_type" {
  description = "Tipo de nodo de ElastiCache (free tier)"
  type        = string
  default     = "cache.t3.micro"
}

variable "lambda_runtime" {
  description = "Runtime de Node.js para la Lambda"
  type        = string
  default     = "nodejs20.x"
}

variable "lambda_timeout" {
  description = "Timeout de la Lambda en segundos"
  type        = number
  default     = 10
}

variable "lambda_memory" {
  description = "Memoria asignada a la Lambda en MB"
  type        = number
  default     = 256
}

variable "cache_ttl_seconds" {
  description = "TTL (segundos) que se guarda cada item en Redis"
  type        = number
  default     = 300
}
