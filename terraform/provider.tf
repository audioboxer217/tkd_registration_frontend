terraform {
  cloud {
    hostname     = "app.terraform.io"
    organization = "OKTKD"
    workspaces {
      tags = [
        "tkd_reg",
        "infra"
      ]
    }
  }
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}
