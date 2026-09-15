# AMI de Amazon Linux 2023 más reciente (se resuelve dinámicamente según la región)
data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Key pair nuevo generado por Terraform para acceso SSH
resource "tls_private_key" "lab1_key" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "lab1_key" {
  key_name   = var.key_name
  public_key = tls_private_key.lab1_key.public_key_openssh
}

# Guarda la llave privada en esta misma carpeta para poder hacer SSH
resource "local_file" "private_key" {
  content         = tls_private_key.lab1_key.private_key_pem
  filename        = "${path.module}/${var.key_name}.pem"
  file_permission = "0400"
}

resource "aws_security_group" "lab1_sg" {
  name        = "lab1-ec2-sg"
  description = "Security group para la instancia EC2 del lab1 (permite SSH y HTTP)"

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Salida completa"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "lab1-ec2-sg"
  }
}

resource "aws_instance" "lab1" {
  ami                         = data.aws_ami.amazon_linux.id
  instance_type               = var.instance_type
  key_name                    = aws_key_pair.lab1_key.key_name
  vpc_security_group_ids      = [aws_security_group.lab1_sg.id]
  user_data                   = file("${path.module}/user_data.sh")
  user_data_replace_on_change = true

  tags = {
    Name = var.instance_name
  }
}
