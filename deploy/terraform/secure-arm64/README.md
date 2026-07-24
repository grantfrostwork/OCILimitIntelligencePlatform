# Secure ARM64 Network Stack

This stack performs a blue-green network migration for the ARM64 OCI Limit Intelligence Platform.
It leaves the existing public VM untouched and creates:

- a private regional subnet with no public VNICs;
- a NAT Gateway for outbound OCI regional API access;
- separate load-balancer and application NSGs;
- a 2 OCPU / 12 GB Ampere A1 VM with IMDSv2 enforced;
- a public Flexible Load Balancer with an HTTP health check;
- an OCI Bastion for temporary administrative SSH sessions; and
- an optional HTTPS listener backed by OCI Certificates.

The stack does not create or modify IAM policies. See
[`docs/runtime-iam-policies.md`](../../../docs/runtime-iam-policies.md) before removing the current
broad instance-principal access.

## Two-Stage TLS Deployment

First apply with `certificate_id = ""`. This creates an HTTP listener so cloud-init and backend
health can be validated. The HTTP listener forwards the ACME challenge path to the private VM; the
frontend redirects all other HTTP requests to HTTPS after a certificate is configured.

For an IP-only deployment, set `LIP_CERTIFICATE_IP`, `LETSENCRYPT_EMAIL`, and the certificate
compartment values in `/opt/oci-lip/.env`, then run:

```bash
sudo /opt/oci-lip/deploy/arm64/request-ip-certificate.sh --staging
sudo /opt/oci-lip/deploy/arm64/request-ip-certificate.sh
```

The production command creates the initial imported OCI Certificates resource when
`LIP_CERTIFICATE_ID` is empty. Read the certificate OCID from the command output or the persistent
`certificate-status` Docker volume, put it in `.env` and `terraform.tfvars`, and apply again.

Set `certificate_id` to that certificate OCID and apply again. Terraform then adds the TLS 1.2/1.3
listener. Private keys are never accepted by this stack and therefore do not enter Terraform
state. Install `oci-lip-certificate-renew.timer` after the listener serves the IP certificate.

## Commands

```bash
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform fmt -recursive
terraform validate
terraform plan -out secure-arm64.tfplan
terraform apply secure-arm64.tfplan
```

Use a remote encrypted Terraform state backend for a customer deployment. The local state file is
excluded from Git but is still sensitive operational data.
