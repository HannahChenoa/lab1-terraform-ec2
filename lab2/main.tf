data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# AMI de Amazon Linux 2023 más reciente
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
resource "tls_private_key" "lab2_key" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "lab2_key" {
  key_name   = var.key_name
  public_key = tls_private_key.lab2_key.public_key_openssh
}

resource "local_file" "private_key" {
  content         = tls_private_key.lab2_key.private_key_pem
  filename        = "${path.module}/${var.key_name}.pem"
  file_permission = "0400"
}

# --- Certificado HTTPS autofirmado (gratis, sin necesidad de dominio) ---
# Generamos nuestra propia llave + certificado, y lo importamos a ACM.
# ACM en modo "import" no valida dominio (a diferencia de pedir uno nuevo),
# así que no necesitamos Route53 ni comprar nada.
resource "tls_private_key" "cert_key" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_self_signed_cert" "alb_cert" {
  private_key_pem = tls_private_key.cert_key.private_key_pem

  subject {
    common_name  = "lab2.local"
    organization = "ITESO DSE Lab2"
  }

  validity_period_hours = 8760 # 1 año

  allowed_uses = [
    "key_encipherment",
    "digital_signature",
    "server_auth",
  ]
}

resource "aws_acm_certificate" "self_signed" {
  private_key      = tls_private_key.cert_key.private_key_pem
  certificate_body = tls_self_signed_cert.alb_cert.cert_pem

  lifecycle {
    create_before_destroy = true
  }
}

# Security group del ALB: recibe HTTP y HTTPS de internet
resource "aws_security_group" "alb_sg" {
  name        = "lab2-alb-sg"
  description = "Security group del Application Load Balancer (HTTP + HTTPS)"

  ingress {
    description = "HTTP desde internet"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS desde internet"
    from_port   = 443
    to_port     = 443
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
    Name = "lab2-alb-sg"
  }
}

# Security group de las instancias: solo reciben HTTP del ALB, + SSH
resource "aws_security_group" "instances_sg" {
  name        = "lab2-instances-sg"
  description = "Security group de las instancias EC2 (HTTP solo desde el ALB, + SSH)"

  ingress {
    description     = "HTTP solo desde el ALB"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
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
    Name = "lab2-instances-sg"
  }
}

# Las 2 instancias EC2 estáticas
resource "aws_instance" "web" {
  count                  = 2
  ami                    = data.aws_ami.amazon_linux.id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.lab2_key.key_name
  subnet_id              = data.aws_subnets.default.ids[count.index % length(data.aws_subnets.default.ids)]
  vpc_security_group_ids = [aws_security_group.instances_sg.id]

  user_data = templatefile("${path.module}/user_data.sh.tpl", {
    server_name = "VM-${count.index + 1}"
  })

  tags = {
    Name = "lab2-web-${count.index + 1}"
  }
}

# Application Load Balancer
resource "aws_lb" "app" {
  name               = "lab2-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]
  subnets            = data.aws_subnets.default.ids

  tags = {
    Name = "lab2-alb"
  }
}

# Target group - round robin (algoritmo por defecto del ALB)
resource "aws_lb_target_group" "app" {
  name        = "lab2-tg"
  port        = 80
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.default.id
  target_type = "instance"

  load_balancing_algorithm_type = "round_robin"

  health_check {
    path                = "/"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }

  tags = {
    Name = "lab2-tg"
  }
}

resource "aws_lb_target_group_attachment" "web" {
  count            = 2
  target_group_arn = aws_lb_target_group.app.arn
  target_id        = aws_instance.web[count.index].id
  port             = 80
}

# Listener HTTP: redirige todo a HTTPS
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# Listener HTTPS: usa el certificado autofirmado importado a ACM
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.app.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-2016-08"
  certificate_arn   = aws_acm_certificate.self_signed.arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}
