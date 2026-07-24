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

resource "oci_load_balancer_rule_set" "https_redirect" {
  count = var.certificate_id == "" ? 0 : 1

  load_balancer_id = oci_load_balancer_load_balancer.lip.id
  name             = "redirect_to_https"

  items {
    action        = "REDIRECT"
    response_code = 301

    conditions {
      attribute_name  = "PATH"
      attribute_value = "/"
      operator        = "FORCE_LONGEST_PREFIX_MATCH"
    }

    redirect_uri {
      protocol = "HTTPS"
      port     = 443
      host     = "{host}"
      path     = "{path}"
      query    = "{query}"
    }
  }
}

resource "oci_load_balancer_listener" "http" {
  load_balancer_id         = oci_load_balancer_load_balancer.lip.id
  name                     = "http"
  default_backend_set_name = oci_load_balancer_backend_set.lip.name
  port                     = 80
  protocol                 = "HTTP"
  rule_set_names = (
    var.certificate_id == ""
    ? []
    : [oci_load_balancer_rule_set.https_redirect[0].name]
  )
}

resource "oci_load_balancer_listener" "https" {
  count = var.certificate_id == "" ? 0 : 1

  load_balancer_id         = oci_load_balancer_load_balancer.lip.id
  name                     = "https"
  default_backend_set_name = oci_load_balancer_backend_set.lip.name
  port                     = 443
  protocol                 = "HTTP"

  ssl_configuration {
    certificate_ids         = [var.certificate_id]
    protocols               = ["TLSv1.2", "TLSv1.3"]
    cipher_suite_name       = "oci-default-ssl-cipher-suite-v1"
    server_order_preference = "ENABLED"
    verify_peer_certificate = false
  }
}
