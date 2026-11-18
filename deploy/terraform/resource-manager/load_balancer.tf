resource "oci_core_public_ip" "lip" {
  compartment_id = local.compartment_ocid
  lifetime       = "RESERVED"
  display_name   = var.deployment_name
  lifecycle { ignore_changes = [private_ip_id] }
}
resource "oci_load_balancer_load_balancer" "lip" {
  compartment_id             = local.compartment_ocid
  display_name               = var.deployment_name
  shape                      = "flexible"
  subnet_ids                 = [oci_core_subnet.public.id]
  network_security_group_ids = [oci_core_network_security_group.load_balancer.id]
  reserved_ips { id = oci_core_public_ip.lip.id }
  shape_details {
    minimum_bandwidth_in_mbps = 10
    maximum_bandwidth_in_mbps = 10
  }
}
resource "oci_load_balancer_backend_set" "lip" {
  load_balancer_id = oci_load_balancer_load_balancer.lip.id
  name             = "application"
  policy           = "ROUND_ROBIN"
  health_checker {
    protocol    = "HTTP"
    port        = 80
    url_path    = "/healthz"
    return_code = 200
  }
}
resource "oci_load_balancer_backend" "lip" {
  load_balancer_id = oci_load_balancer_load_balancer.lip.id
  backendset_name  = oci_load_balancer_backend_set.lip.name
  ip_address       = oci_core_instance.lip.private_ip
  port             = 80
}
resource "oci_load_balancer_listener" "https" {
  load_balancer_id         = oci_load_balancer_load_balancer.lip.id
  name                     = "https"
  default_backend_set_name = oci_load_balancer_backend_set.lip.name
  port                     = 443
  protocol                 = "HTTP"
  ssl_configuration {
    certificate_ids         = [var.certificate_ocid]
    verify_peer_certificate = false
    protocols               = ["TLSv1.2", "TLSv1.3"]
    cipher_suite_name       = "oci-default-http2-tls-12-13-ssl-cipher-suite-v1"
  }
}
