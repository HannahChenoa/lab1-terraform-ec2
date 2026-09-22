# --- Red: usamos la VPC default y sus subnets (igual que lab2/lab3) ---
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# --- IAM: en AWS Academy no se pueden crear roles nuevos (iam:CreateRole
# está denegado), así que reutilizamos el LabRole que ya trae la cuenta ---
data "aws_iam_role" "lab_role" {
  name = var.lambda_role_name
}

# --- Password de RDS generado dinámicamente (nunca queda en texto plano en el repo) ---
resource "random_password" "db_password" {
  length  = 20
  special = false
}

# ------------------------- Security Groups -------------------------

resource "aws_security_group" "alb_sg" {
  name        = "lab4-alb-sg"
  description = "Security group del ALB (HTTP desde internet)"
  vpc_id      = data.aws_vpc.default.id

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

  tags = { Name = "lab4-alb-sg" }
}

resource "aws_security_group" "lambda_sg" {
  name        = "lab4-lambda-sg"
  description = "Security group de la Lambda (sale a RDS y ElastiCache dentro de la VPC)"
  vpc_id      = data.aws_vpc.default.id

  egress {
    description = "Salida completa"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "lab4-lambda-sg" }
}

resource "aws_security_group" "rds_sg" {
  name        = "lab4-rds-sg"
  description = "Security group de RDS (solo acepta MySQL desde la Lambda)"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "MySQL solo desde la Lambda"
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda_sg.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "lab4-rds-sg" }
}

resource "aws_security_group" "cache_sg" {
  name        = "lab4-cache-sg"
  description = "Security group de ElastiCache (solo acepta Redis desde la Lambda)"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "Redis solo desde la Lambda"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda_sg.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "lab4-cache-sg" }
}

# ------------------------------ RDS (MySQL) ------------------------------

resource "aws_db_subnet_group" "lab4" {
  name       = "lab4-db-subnet-group"
  subnet_ids = data.aws_subnets.default.ids

  tags = { Name = "lab4-db-subnet-group" }
}

resource "aws_db_instance" "lab4" {
  identifier              = "lab4-mysql"
  engine                  = "mysql"
  engine_version          = "8.0"
  instance_class          = var.db_instance_class
  allocated_storage       = 20
  db_name                 = var.db_name
  username                = var.db_username
  password                = random_password.db_password.result
  db_subnet_group_name    = aws_db_subnet_group.lab4.name
  vpc_security_group_ids  = [aws_security_group.rds_sg.id]
  publicly_accessible     = false
  skip_final_snapshot     = true
  multi_az                = false
  apply_immediately       = true
  backup_retention_period = 0

  tags = { Name = "lab4-mysql" }
}

# --------------------------- ElastiCache (Redis) ---------------------------

resource "aws_elasticache_subnet_group" "lab4" {
  name       = "lab4-cache-subnet-group"
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_elasticache_cluster" "lab4" {
  cluster_id         = "lab4-redis"
  engine             = "redis"
  engine_version     = "7.0"
  node_type          = var.cache_node_type
  num_cache_nodes    = 1
  port               = 6379
  subnet_group_name  = aws_elasticache_subnet_group.lab4.name
  security_group_ids = [aws_security_group.cache_sg.id]

  tags = { Name = "lab4-redis" }
}

# ------------------------- Empaquetado de la Lambda -------------------------
# Instala las dependencias de Node (mysql2, ioredis -> son 100% JS, no requieren
# compilación nativa) y arma el zip que se sube a Lambda.

resource "null_resource" "lambda_npm_install" {
  triggers = {
    package_json = filesha256("${path.module}/lambda/package.json")
  }

  provisioner "local-exec" {
    command     = "npm install --production"
    working_dir = "${path.module}/lambda"
  }
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/lambda"
  output_path = "${path.module}/lambda_function.zip"

  depends_on = [null_resource.lambda_npm_install]
}

# --------------------------------- Lambda ---------------------------------

resource "aws_lambda_function" "app" {
  function_name    = "lab4-app"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  handler          = "index.handler"
  runtime          = var.lambda_runtime
  role             = data.aws_iam_role.lab_role.arn
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory

  vpc_config {
    subnet_ids         = data.aws_subnets.default.ids
    security_group_ids = [aws_security_group.lambda_sg.id]
  }

  environment {
    variables = {
      DB_HOST           = aws_db_instance.lab4.address
      DB_PORT           = tostring(aws_db_instance.lab4.port)
      DB_USER           = var.db_username
      DB_PASSWORD       = random_password.db_password.result
      DB_NAME           = var.db_name
      REDIS_HOST        = aws_elasticache_cluster.lab4.cache_nodes[0].address
      REDIS_PORT        = tostring(aws_elasticache_cluster.lab4.cache_nodes[0].port)
      CACHE_TTL_SECONDS = tostring(var.cache_ttl_seconds)
    }
  }

  tags = { Name = "lab4-app" }
}

resource "aws_lambda_permission" "alb_invoke" {
  statement_id  = "AllowALBInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.app.function_name
  principal     = "elasticloadbalancing.amazonaws.com"
  source_arn    = aws_lb_target_group.app.arn
}

# ----------------------------------- ALB -----------------------------------

resource "aws_lb" "app" {
  name               = "lab4-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]
  subnets            = data.aws_subnets.default.ids

  tags = { Name = "lab4-alb" }
}

resource "aws_lb_target_group" "app" {
  name        = "lab4-tg"
  target_type = "lambda"

  health_check {
    enabled = true
    path    = "/health"
    matcher = "200"
  }
}

resource "aws_lb_target_group_attachment" "lambda" {
  target_group_arn = aws_lb_target_group.app.arn
  target_id        = aws_lambda_function.app.arn

  depends_on = [aws_lambda_permission.alb_invoke]
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
