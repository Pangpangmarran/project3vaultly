terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "vaultly-tf-state-686699774218"
    key            = "vaultly/main.tfstate"
    region         = "eu-central-1"
    dynamodb_table = "vaultly-tf-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = "eu-central-1"
}

# Test resource — proves the backend works
resource "aws_s3_bucket" "test" {
  bucket = "vaultly-test-686699774218"

  tags = {
    Project = "vaultly"
    Purpose = "backend verification"
  }
}   
