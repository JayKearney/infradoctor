# Example VPC layout. One range collides with another VPC.

resource "aws_vpc" "prod" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  tags = { Name = "prod" }
}

resource "aws_subnet" "prod_private_a" {
  vpc_id     = aws_vpc.prod.id
  cidr_block = "10.0.1.0/24" # inside prod by design: not reported
}

resource "aws_vpc" "staging" {
  cidr_block = "10.1.0.0/16"
  tags = { Name = "staging" }
}

resource "aws_vpc" "data_platform" {
  cidr_block = "10.0.128.0/20" # overlaps prod: peering would break
  tags = { Name = "data-platform" }
}

resource "aws_vpc_ipv4_cidr_block_association" "staging_secondary" {
  vpc_id     = aws_vpc.staging.id
  cidr_block = "100.64.0.0/16"
}