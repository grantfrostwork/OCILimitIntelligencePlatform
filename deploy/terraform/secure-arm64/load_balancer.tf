resource "oci_load_balancer_load_balancer" "lip" {
  compartment_id             = local.compartment_ocid
  display_name               = "oci-lip-flexible-load-balancer"
  shape                      = "flexible"
  is_private                 = false
  network_security_group_ids = [oci_core_network_security_group.load_balancer.id]
  subnet_ids                 = [var.public_subnet_id]
  freeform_tags              = local.common_tags

  shape_details {
    minimum_bandwidth_in_mbps = var.load_balancer_min_bandwidth_mbps
    maximum_bandwidth_in_mbps = var.load_balancer_max_bandwidth_mbps
  }
}

resource "oci_load_balancer_backend_set" "lip" {
  load_balancer_id = oci_load_balancer_load_balancer.lip.id
  name             = "oci-lip-backends"
  policy           = "ROUND_ROBIN"

  health_checker {
    protocol          = "HTTP"
    port              = 80
    url_path          = "/healthz"
    return_code       = 200
    interval_ms       = 10000
    timeout_in_millis = 3000
    retries           = 3
  }
}

resource "oci_load_balancer_backend" "lip" {
  load_balancer_id = oci_load_balancer_load_balancer.lip.id
  backendset_name  = oci_load_balancer_backend_set.lip.name
  ip_address       = oci_core_instance.lip.private_ip
  port             = 80
  weight           = 1
}

resource "oci_load_balancer_listener" "http" {
  load_balancer_id         = oci_load_balancer_load_balancer.lip.id
  name                     = "http"
  default_backend_set_name = oci_load_balancer_backend_set.lip.name
  port                     = 80
  protocol                 = "HTTP"
  rule_set_names           = []
}

resource "oci_load_balancer_listener" "https" {
  count = local.https_enabled ? 1 : 0

  load_balancer_id         = oci_load_balancer_load_balancer.lip.id
  name                     = "https"
  default_backend_set_name = oci_load_balancer_backend_set.lip.name
  port                     = 443
  protocol                 = "HTTP"

  ssl_configuration {
    certificate_ids         = var.certificate_id != "" ? [var.certificate_id] : null
    certificate_name        = var.load_balancer_certificate_name != "" ? var.load_balancer_certificate_name : null
    protocols               = ["TLSv1.2", "TLSv1.3"]
    cipher_suite_name       = "oci-default-ssl-cipher-suite-v1"
    server_order_preference = "ENABLED"
    verify_peer_certificate = false
  }

  lifecycle {
    ignore_changes = [
      ssl_configuration[0].certificate_ids,
      ssl_configuration[0].certificate_name,
    ]
  }
}
