# Secure ARM64 Network Stack

This stack performs a blue-green network migration for the ARM64 OCI Limit Intelligence Platform.
It leaves the existing public VM untouched and creates:

- a private regional subnet with no public VNICs;
- a NAT Gateway for outbound OCI regional API access;
- separate load-balancer and application NSGs;
- a 2 OCPU / 12 GB Ampere A1 VM with IMDSv2 enforced;
- a public Flexible Load Balancer with an HTTP health check;
- an OCI Bastion for temporary administrative SSH sessions; and
- an optional HTTPS listener backed by a Load Balancer-managed certificate bundle.

The stack does not create or modify IAM policies. See
[`docs/runtime-iam-policies.md`](../../../docs/runtime-iam-policies.md) before removing the current
broad instance-principal access.

## Two-Stage TLS Deployment

First apply with both `certificate_id = ""` and `load_balancer_certificate_name = ""`. This creates
an HTTP listener so cloud-init and backend health can be validated. The HTTP listener forwards the
ACME challenge path to the private VM; the frontend redirects all other HTTP requests to HTTPS.

For an IP-only deployment, set `LIP_CERTIFICATE_IP`, `LETSENCRYPT_EMAIL`,
`LIP_LOAD_BALANCER_ID`, and the listener settings in `/opt/oci-lip/.env`, then run:

```bash
sudo /opt/oci-lip/deploy/arm64/request-ip-certificate.sh --staging
sudo /opt/oci-lip/deploy/arm64/request-ip-certificate.sh
```

The production command creates an unattached Load Balancer certificate bundle and writes its name
to the command output and the persistent `certificate-status` Docker volume. Set
`load_balancer_certificate_name` to that name and apply again. Terraform then creates the TLS
1.2/1.3 listener.

Private keys are never accepted by this stack and therefore do not enter Terraform state. Run
`renew-certificate.sh` once after the listener exists to verify the public fingerprint, then install
`oci-lip-certificate-renew.timer`. The renewal service owns subsequent listener certificate-name
changes, and Terraform ignores those two SSL association attributes.

An existing installation that still has a load-balancer redirect rule set must detach it before
Terraform deletes it. Apply that upgrade in two stages:

```bash
terraform apply -target=oci_load_balancer_listener.http
terraform apply
```

NGINX then owns both the ACME exception and the HTTP-to-HTTPS redirect.

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
