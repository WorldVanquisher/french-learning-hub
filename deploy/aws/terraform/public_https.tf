# FLH-088 public HTTPS entry point, off by default (public_https_enabled).
#
# Enabled, it adds exactly four resources to the FLH-084 stack:
# - an Elastic IP associated with the existing instance, so the DNS A record
#   survives stop/start;
# - inbound TCP 80 (Let's Encrypt HTTP-01 and the redirect) and TCP 443 from
#   anywhere on IPv4.
# The demo server itself stays on 127.0.0.1:18970; nginx on the host
# (deploy/aws/host/flh-public-https, installed over SSM) terminates TLS and
# proxies to it. Nothing here changes the instance or its user data, so
# enabling or disabling never replaces the instance. Session Manager access is
# unchanged (outbound 443 only).

locals {
  public_https = var.public_https_enabled ? 1 : 0
}

resource "aws_eip" "public" {
  count      = local.public_https
  domain     = "vpc"
  tags       = { Name = "${local.name}-public" }
  depends_on = [aws_internet_gateway.demo]
}

# Associating an Elastic IP releases the instance's auto-assigned public IPv4
# address; disassociating it gives the instance a new auto-assigned one
# (associate_public_ip_address stays true), so outbound SSM keeps working
# either way.
resource "aws_eip_association" "public" {
  count         = local.public_https
  instance_id   = aws_instance.host.id
  allocation_id = aws_eip.public[0].id
}

resource "aws_vpc_security_group_ingress_rule" "http" {
  count             = local.public_https
  security_group_id = aws_security_group.host.id
  description       = "Public HTTP: ACME HTTP-01 challenge and redirect to HTTPS"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  count             = local.public_https
  security_group_id = aws_security_group.host.id
  description       = "Public HTTPS: nginx in front of the loopback demo"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}
