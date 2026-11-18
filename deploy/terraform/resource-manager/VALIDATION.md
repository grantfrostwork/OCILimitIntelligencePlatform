# Customer stack validation

Validated on 2026-11-18:

- Terraform **1.5.7**, matching the documented Resource Manager 1.5.x runtime; Oracle OCI provider **8.24.0**. Formatting and `terraform validate` passed.
- A non-applied plan using example identifiers: **32 resources to add, 0 to change, 0 to destroy**. This checks the graph and input expressions, not the installer's tenancy permissions or OCI service acceptance.
- `schema.yaml` passes Oracle's published Resource Manager meta-schema (Draft 7 validation) and covers every Terraform input once in the guided variable groups.
- Terraform renders valid cloud-init YAML with embedded install/bootstrap/readiness scripts and systemd unit. Decoded user data remains below 32 KiB.
- Shell syntax checks and five bootstrap tests passed, including authentication enabled by default, literal secret punctuation, protected file permissions, credential persistence on OIDC rotation, and refusal to regenerate an incomplete database-secret backup.
- Docker Compose **2.39.4** parses the generated environment correctly, including a synthetic OIDC secret containing dollar signs, quotes and a backslash. No real credentials were used for this check.
- The allowlisted, deterministic ZIP includes all Terraform templates and guest assets; no state, plans, `.env`, local caches or real customer settings.

These are package checks. This new greenfield stack has **not** been applied to a fresh customer tenancy. Real Identity Domain login/logout/RBAC, DNS/TLS, runtime IAM, scans, subscription confirmation and email delivery remain customer installation acceptance checks in README.md. The pre-existing live deployment is not modified by packaging this stack.

Reproduce from the repository:

```bash
terraform -chdir=deploy/terraform/resource-manager init -backend=false
terraform fmt -check deploy/terraform/resource-manager
terraform -chdir=deploy/terraform/resource-manager validate
python3 -m unittest discover -s deploy/terraform/resource-manager/tests -v
bash -n deploy/terraform/resource-manager/install.sh deploy/terraform/resource-manager/ready.sh
# In an isolated Python environment with PyYAML, jsonschema and python-hcl2 installed:
python3 scripts/validate-resource-manager.py
python3 scripts/package-resource-manager.py /tmp/oci-lip-resource-manager.zip
```

The GitHub Actions customer-stack workflow runs these checks and uploads the deployable ZIP. The separate existing ARM64 image workflow validates application image builds.
