# Install OCI Limit Intelligence Platform in your tenancy

This is the recommended **new installation** stack. It creates a dedicated compartment, VCN, public/private subnets, internet/NAT gateways, a private Ampere A1 VM (2 OCPUs, 12 GB memory, 100 GB boot volume), reserved public IP, HTTPS flexible load balancer (10 Mbps), Bastion, runtime dynamic group/policies, and an OCI Notifications topic. PostgreSQL, Prometheus and Grafana run alongside the application on the VM. This is a single-host deployment; it is not highly available.

[![Deploy to Oracle Cloud](https://oci-resourcemanager-plugin.plugins.oci.oraclecloud.com/latest/deploy-to-oracle-cloud.svg)](https://cloud.oracle.com/resourcemanager/stacks/create?zipUrl=https%3A%2F%2Fgithub.com%2Fgrantfrostwork%2FOCILimitIntelligencePlatform%2Freleases%2Fdownload%2Fcustomer-stack-v1.0.0%2Foci-lip-resource-manager.zip)

[Download the stack ZIP](https://github.com/grantfrostwork/OCILimitIntelligencePlatform/releases/download/customer-stack-v1.0.0/oci-lip-resource-manager.zip). The ZIP has `schema.yaml` and Terraform files at its root, with all guest bootstrap assets included. No local file paths or infrastructure from the author's tenancy are required. The existing `secure-arm64` directory is a separate migration configuration; do not apply both stacks to the same installation.

## 1. Prepare prerequisites

Use a commercial OCI tenancy with subscribed deployment and Vault regions, an Identity Domain, A1 capacity (2 OCPUs / 12 GB) in your selected AD, and quota for one VCN, NAT gateway, flexible load balancer, reserved public IP, 100 GB boot volume, Bastion and Notifications topic. These resources can incur charges; review your pricing and quotas before Apply. No Always Free eligibility is assumed. Outbound internet is required for GitHub, package/container registries, OCI APIs and OIDC discovery/JWKS.

Have a tenancy administrator run the stack or grant the installer equivalent rights to create a child compartment, manage its compute/network/load-balancer/Bastion/Notifications resources, manage dynamic groups and root-attached policies, inspect available images/ADs, and use the existing TLS certificate. An Identity Domain administrator configures SSO separately; a Vault administrator creates the secret. Resource Manager execution must have the same infrastructure permissions. This installer creates tenancy-wide **read access to service limits and compartments** for its runtime and IAM objects in the tenancy home region. It does not grant runtime compute/network creation privileges. Review `main.tf` before approving the plan.

Choose a unique `deployment_name`, an unused IPv4 `/16` VCN range, administrator SSH public key, narrow Bastion source CIDRs, and allowed application HTTPS source CIDRs. The VM has no public IP; only the load balancer accepts HTTPS. Public HTTP has no listener. Supply the public key itself, never a private key. IMDSv1 is disabled.

### Hostname and certificate

For this customer stack, use a customer-controlled hostname such as `limits.example.com`. Obtain a publicly trusted certificate covering it, including its chain, and import/manage it in **OCI Certificates in the deployment region**. Record its certificate OCID. The stack associates this existing certificate with its TLS 1.2/1.3 listener; private certificate keys do not enter Terraform variables or state. Arrange certificate renewal through your certificate-management process. A DNS A record is created by your DNS administrator **after** the stack returns its reserved IP.

The IP-certificate automation in the older deployment is not part of this installer. A stable customer hostname lets you prepare TLS and the exact OIDC callback before the VM is created.

### OCI IAM Identity Domain SSO

1. Create groups `OCI-LIP-Viewers`, `OCI-LIP-Operators`, and `OCI-LIP-Admins` in the selected Identity Domain. Add your administrators to the Admin group. Group names can be customized in the Vault JSON below.
2. Create an integrated **Confidential Application**, enable its OAuth client, and enable **Authorization Code** grant. Use client-secret authentication. Set redirect URI to exactly `https://limits.example.com/api/auth/callback` and post-logout redirect URI to `https://limits.example.com/`. Replace the hostname everywhere with your chosen origin.
3. Request scopes `openid profile email approles groups`. Enable **Enforce grants as authorization** and **Bypass consent**. Create an application role (for example `OCI LIP Access`) available to groups, and grant it to all three LIP groups. Activate the application. Being in a LIP group alone does not substitute for the OAuth application-role grant.
4. Configure the application's sign-on policy to allow the intended customer identity provider and client network, preserving your organization's MFA requirements. If a dedicated policy is needed, assign it only to this application. Do not weaken a tenancy-wide policy to fix an application login.
5. Enable the Identity Domain's **Access Signing Certificate → Allow clients to access signing certificate without signing in** option if its discovery JWKS is protected. This exposes public signature-verification keys, not private keys. Verify that the OIDC discovery document and its `jwks_uri` are retrievable over verified HTTPS without an interactive session.
6. Record the client ID, client secret, and domain discovery URL (`https://YOUR-DOMAIN.identity.oraclecloud.com/.well-known/openid-configuration`). Include at least one trusted, assigned user's email in `admin_emails`. Those addresses receive Admin role **after successful OIDC authentication**; there is no local application username/password login.

See the [authentication design and troubleshooting guide](https://github.com/grantfrostwork/OCILimitIntelligencePlatform/blob/codex/arm64-a1-deployment/docs/secure-access-and-network.md) for background. Use this guide's customer-specific values for installation.

### Store the SSO settings in OCI Vault

Create a Vault secret in a compartment you administer, backed by an appropriate symmetric encryption key. In the secret creation UI, select **plaintext** input and paste JSON using the structure in `oidc-secret.example.json`:

```json
{
  "discovery_url": "https://YOUR-DOMAIN.identity.oraclecloud.com/.well-known/openid-configuration",
  "client_id": "YOUR-CLIENT-ID",
  "client_secret": "YOUR-CLIENT-SECRET",
  "admin_emails": ["admin@example.com"],
  "viewer_groups": ["OCI-LIP-Viewers"],
  "operator_groups": ["OCI-LIP-Operators"],
  "admin_groups": ["OCI-LIP-Admins"]
}
```

Keep this secret outside the new application compartment so teardown cannot accidentally remove it. Record the **secret OCID** and its region. Supply only those identifiers to Terraform. The VM fetches the CURRENT version directly using its instance principal and a policy limited to that secret. Terraform never reads the secret bundle. Do not paste client secrets into stack variables, user data, command-line arguments, or committed files.

The VM generates database, Grafana and session secrets locally. Root-owned files `/opt/oci-lip/.env` and `/etc/oci-lip/generated-secrets.json` are mode 600. Guest root, Docker administrators and backups can access them; protect those privileges and backups accordingly. There is no shared/default application password.

## 2. Create and apply the stack

1. Use **Deploy to Oracle Cloud** above, or download the ZIP and choose **Developer Services → Resource Manager → Stacks → Create stack → My configuration → ZIP file**. Use the ZIP root as the working directory. Select Terraform **1.5.x (1.5.7)**.
2. Select the deployment region. Enter your tenancy, parent compartment, tenancy **home region**, unique deployment name, and AD. The stack creates its own child compartment; the compartment selected to store the Resource Manager stack can be elsewhere.
3. Supply an Oracle Linux **9 ARM64** platform image OCID from the deployment region compatible with `VM.Standard.A1.Flex`. Pin this OCID. Do not use an x86 image. You can find candidates with the read-only OCI CLI command below (DEFAULT profile).
4. Fill in the SSH key, client CIDRs, HTTPS origin, existing certificate OCID, Vault secret OCID and Vault region. Decide whether to scan only the deployment region (default) or all subscribed regions. Initial alert defaults are warning 90%, critical 98%; warning must be below critical. Email sending starts **disabled** until configured in Settings.
5. Disable automatic Apply if offered. Create the stack, run **Plan**, and review the compartment, IAM policies, networking and costs. Run **Apply** after accepting that plan. The VM's pinned application commit defaults to the tested alert-settings release; it does not clone a moving branch.
6. Set your hostname's DNS A record to the `dns_a_record` output. Wait for DNS propagation. Keep the hostname identical to `public_url`, certificate SAN, OIDC callback and logout URI.

Example image lookup (replace the compartment with one you can inspect):

```bash
oci compute image list --profile DEFAULT --region us-ashburn-1 \
  --compartment-id '<YOUR-COMPARTMENT-OCID>' \
  --operating-system 'Oracle Linux' --shape VM.Standard.A1.Flex \
  --sort-by TIMECREATED --sort-order DESC --all \
  --query 'data[].{name:"display-name",id:id}' --output table
```

Choose a full Oracle Linux 9 ARM64 image from those results, not a minimal/special-purpose image. The stack uses IMDSv2-only metadata access. IAM dynamic-group propagation can delay secret access; bootstrap retries for up to 30 minutes. Building images on the VM also takes time. **Terraform Apply success confirms infrastructure creation, not application readiness or successful customer login.**

### Local Terraform alternative

Install Terraform 1.5.7 (or compatible `<2.0`) and configure OCI CLI/SDK API-key authentication with your DEFAULT profile. Use a suitably authorized account.

```bash
unzip oci-lip-resource-manager.zip -d oci-lip-stack
cd oci-lip-stack
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your non-secret identifiers and public SSH key.
terraform init
terraform fmt -check
terraform validate
terraform plan -out=install.tfplan
terraform apply install.tfplan
terraform output
```

Do not commit `.terraform`, state, saved plans or real tfvars. State contains infrastructure identifiers and SSH public key, but this stack does not create or retrieve secret values through Terraform. Keep state access restricted.

## 3. Verify the installation

Create a **Managed SSH** session through the Bastion console using the `bastion_ocid`, `instance_ocid` and `instance_private_ip` outputs, OS user `opc`, and your SSH public key. Your current public egress IP must be covered by the Bastion allowlist. Wait for the Bastion agent plugin to become available. Use the console-generated SSH command and your corresponding private key on your own workstation. SSH access to Docker/root gives access to application secrets.

On the guest:

```bash
sudo cloud-init status --wait
sudo systemctl status oci-lip --no-pager
sudo journalctl -u oci-lip --no-pager -n 100
cd /opt/oci-lip
sudo docker compose -f docker-compose.yml -f docker-compose.arm64.yml ps
curl --fail http://127.0.0.1/readyz
```

If bootstrap failed (for example because IAM has not propagated or the Vault region is wrong), correct the prerequisite/configuration and rerun `sudo /usr/local/sbin/oci-lip-install`. It preserves existing generated database/session secrets. Inspect `/var/log/cloud-init-output.log`; do not share secret files or full `docker compose config` output. The installer never deliberately prints secret values.

From a permitted client, verify TLS without `-k`:

```bash
curl --fail https://limits.example.com/readyz
# Protected API must return 401 without a session:
curl -s -o /dev/null -w '%{http_code}\n' https://limits.example.com/api/dashboard
```

In a fresh browser session:

- Sign in with the assigned customer's OCI Identity Domain user and complete MFA. Verify the callback returns to the app, your role is Admin, and Grafana opens through the same login.
- Sign out. Protected API access must again require authentication; sign in again. Test a Viewer account and verify it cannot change alert settings.
- Run a scan in the configured region(s). Confirm successful limit collection and check errors/coverage rather than treating a failed service lookup as zero usage. Set your preferred schedule.
- In **Settings → Alerts**, set warning/critical thresholds, customize subject/body, add recipients and enable notifications. Each recipient must click OCI Notifications' confirmation email before delivery works. Adding an address alone does not activate it. The application manages subscriptions; avoid independently managing them in Terraform.
- Run a scan against a known limit above the warning threshold. Confirm a dashboard alert and an actual delivered email with the intended message. Muted limits must not email. Repeated alerts are deduplicated for six hours; testing again immediately may not generate another email. Threshold settings saved in the database take precedence over initial environment defaults.
- Reboot the VM during an agreed test window and verify service recovery, retained scan history/settings, real SSO and email behavior again.

[Alert settings and template guide](https://github.com/grantfrostwork/OCILimitIntelligencePlatform/blob/codex/arm64-a1-deployment/docs/alert-settings.md).

## Operations, updates and removal

**Backups:** PostgreSQL and other Compose named volumes are on the boot volume. Before upgrades or destroy, take and verify a PostgreSQL backup (for example `sudo docker compose exec -T postgres pg_dump -U lip lip > lip-backup.sql` from the application directory), copy it to approved protected storage, and test restore separately. Boot-volume backups complement database backups. Deleting/replacing the VM can lose local data. This stack does not automatically configure backups or HA.

**SSO secret rotation:** Publish an updated CURRENT Vault secret version. On the VM run `sudo /opt/oci-lip-bootstrap/bin/python /usr/local/lib/oci-lip/bootstrap.py`, then `sudo systemctl restart oci-lip`. The secret is fetched at installation/manual refresh, not continuously on every request. Database and session secrets are preserved. To revoke sessions, deliberately rotate the session secret in the protected generated-secret file, rerun bootstrap and restart. Verify a fresh real login after any change.

**Application upgrades:** Back up first. On the VM, fetch and checkout a reviewed full Git commit in `/opt/oci-lip`, then `sudo systemctl restart oci-lip`. The service builds images, waits for PostgreSQL and runs Alembic migrations before starting the full stack. Verify auth, readiness, scans and email again. Schema migrations may prevent simply checking out an older commit; use a tested database restore for rollback. Terraform ignores changes to initial user data so modifying `application_commit` on an existing stack does **not** silently replace the database VM or upgrade the guest. For an existing VM, update `/etc/oci-lip/config.json` as well if you intend to rerun the installer; its `commit` controls installer checkout. Other bootstrap inputs, such as scan defaults/secret OCID/origin, similarly require updating that guest configuration and rerunning bootstrap. Network/IAM changes still use normal Terraform plans.

**Certificate rotation:** Renew the existing OCI Certificates object through your approved process; the listener references its OCID. If you replace the entire certificate object, update `certificate_ocid` and apply the reviewed plan. Never allow the certificate to expire unnoticed.

**Troubleshooting:** A 502 usually means bootstrap/containers are not ready; check guest logs and backend health. A1 `Out of host capacity` requires another AD/region or a later retry. `NotAuthorizedOrNotFound` fetching Vault requires checking the secret OCID/region and runtime policy plus IAM propagation. OIDC `internal_server_error` requires reviewing Identity Domain audit/sign-on policy/application-role grants; verify redirect URI, consent, scopes and public JWKS before changing MFA policies. Delivery failures require confirmed subscriptions, notifications enabled, correct thresholds and an unmuted limit; deduplication can suppress immediate repeats.

**Removal:** Stop scans and back up/verify data first. Run a Resource Manager Destroy job (or a reviewed local `terraform plan -destroy` followed by `terraform destroy`). This deletes stack-owned infrastructure, its IAM policy/dynamic group, topic/subscriptions and dedicated compartment, subject to OCI dependency/deletion delays. OCI can retain a detached boot volume; inspect retained volumes/backups and delete only after confirming you have the data you need. External DNS, Identity Domain app/groups, Vault secret/key and TLS certificate are customer-owned prerequisites and remain for your administrator to retire separately. Remove those integrations when no longer needed.

## Package validation and scope

The release is checked with Terraform 1.5.7, the pinned Oracle OCI provider 8.24.0, Oracle's Resource Manager schema meta-schema, rendered cloud-init parsing, shell syntax and bootstrap tests. A plan using example identifiers can check dependency construction without creating resources. Fresh customer-tenancy Apply, provider permissions, available capacity, DNS/TLS ownership, real SSO and confirmed email delivery must be validated during your acceptance procedure above; local validation does not establish those outcomes.

Reference: [Resource Manager Terraform versions](https://docs.oracle.com/en-us/iaas/Content/ResourceManager/Reference/terraformversions.htm), [configuration schema](https://docs.oracle.com/en-us/iaas/Content/ResourceManager/Concepts/terraformconfigresourcemanager_topic-schema.htm), [Deploy button](https://docs.oracle.com/en-us/iaas/Content/ResourceManager/Tasks/deploybutton.htm).
