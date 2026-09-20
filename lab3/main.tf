data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

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

resource "tls_private_key" "lab3_key" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "lab3_key" {
  key_name   = var.key_name
  public_key = tls_private_key.lab3_key.public_key_openssh
}

resource "local_file" "private_key" {
  content         = tls_private_key.lab3_key.private_key_pem
  filename        = "${path.module}/${var.key_name}.pem"
  file_permission = "0400"
}

# Security group del ALB: recibe HTTP de internet
resource "aws_security_group" "alb_sg" {
  name        = "lab3-alb-sg"
  description = "Security group del Application Load Balancer (HTTP)"

  ingress {
    description = "HTTP desde internet"
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
    Name = "lab3-alb-sg"
  }
}

# Security group de las instancias del autoscaling
resource "aws_security_group" "instances_sg" {
  name        = "lab3-instances-sg"
  description = "Security group de las instancias del Auto Scaling Group (HTTP solo desde el ALB, + SSH)"

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
    Name = "lab3-instances-sg"
  }
}

# Launch template: la "plantilla" que usa el Auto Scaling Group para crear instancias nuevas
resource "aws_launch_template" "web" {
  name_prefix   = "lab3-lt-"
  image_id      = data.aws_ami.amazon_linux.id
  instance_type = var.instance_type
  key_name      = aws_key_pair.lab3_key.key_name

  vpc_security_group_ids = [aws_security_group.instances_sg.id]

  user_data = base64encode(file("${path.module}/user_data.sh"))

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "lab3-web"
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Application Load Balancer (igual que en el lab 2)
resource "aws_lb" "app" {
  name               = "lab3-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]
  subnets            = data.aws_subnets.default.ids

  tags = {
    Name = "lab3-alb"
  }
}

resource "aws_lb_target_group" "app" {
  name        = "lab3-tg"
  port        = 80
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.default.id
  target_type = "instance"

  health_check {
    path                = "/"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }

  tags = {
    Name = "lab3-tg"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

# Auto Scaling Group: arranca con 1 instancia, escala hasta 3 según CPU
resource "aws_autoscaling_group" "web" {
  name                = "lab3-asg"
  min_size            = var.asg_min
  max_size            = var.asg_max
  desired_capacity    = var.asg_desired
  vpc_zone_identifier = data.aws_subnets.default.ids
  target_group_arns   = [aws_lb_target_group.app.arn]

  health_check_type         = "ELB"
  health_check_grace_period = 180

  launch_template {
    id      = aws_launch_template.web.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "lab3-web"
    propagate_at_launch = true
  }
}

# Política de escalamiento: sube/baja instancias para mantener la CPU promedio cerca del target
resource "aws_autoscaling_policy" "cpu_target_tracking" {
  name                   = "lab3-scale-cpu"
  autoscaling_group_name = aws_autoscaling_group.web.name
  policy_type            = "TargetTrackingScaling"

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ASGAverageCPUUtilization"
    }
    target_value = var.cpu_target
  }
}
