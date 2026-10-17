terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State local (infra/terraform.tfstate). El bucket "hannah.puente" no existe
  # en la cuenta actual del Learner Lab. Para usar S3 de nuevo:
  #   aws s3 mb s3://hannah.puente --profile academy
  # descomenta el bloque y corre: terraform init -migrate-state
  #
  # backend "s3" {
  #   bucket  = "hannah.puente"
  #   key     = "lab5/terraform.tfstate"
  #   region  = "us-east-1"
  #   profile = "academy"
  # }
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile

  default_tags {
    tags = {
      Proyecto = var.proyecto
      Materia  = "DSE"
      Lab      = "lab5"
    }
  }
}
