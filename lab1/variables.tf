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

variable "instance_type" {
  description = "Tipo de instancia EC2"
  type        = string
  default     = "t2.micro"
}

variable "instance_name" {
  description = "Nombre (tag Name) de la instancia EC2"
  type        = string
  default     = "lab1-ec2-instance"
}

variable "key_name" {
  description = "Nombre del key pair de AWS que se crea para acceso SSH"
  type        = string
  default     = "lab1-key"
}
