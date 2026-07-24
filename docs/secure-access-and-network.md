# Secure Access and Network Migration

## Target Request Path

```text
Browser
  -> public OCI Flexible Load Balancer (TLS 1.2/1.3)
  -> private-subnet NGINX frontend (HTTP inside the VCN)
  -> FastAPI / Grafana / internal Prometheus
```

Only the load balancer has a public address. The application VM has no public IP. Its NSG accepts
port 80 only from the load-balancer NSG and port 22 only from the OCI Bastion private endpoint.
Outbound HTTPS traverses a NAT Gateway so the instance principal can call all selected OCI regional
service endpoints.

## OCI IAM Identity Domain Application

Create one confidential OAuth application in the tenancy's IAM Identity Domain:

| Setting | Value |
| --- | --- |
| Grant type | Authorization code |
| Redirect URI | `https://<lip-fqdn>/api/auth/callback` |
| Post-logout URL | `https://<lip-fqdn>/` |
| Scopes | `openid profile email approles groups` |
| Client type | Confidential |
| Application model | Unmanaged application |
| Access control | Enforce grants as authorization |
| Bypass consent | Enabled |

Create an `OCI LIP Access` application role that is available to groups, then grant that role to
the three LIP groups below. The `approles` scope is required for Oracle IAM to evaluate the
application-role grant and return the group context used by LIP.

Under the Identity Domain's default settings, enable public access to the signing certificate.
This makes the public JWKS in the discovery document readable so LIP can verify ID-token signatures.
It does not expose a private signing key.

The backend merges the validated ID-token claims with Oracle's UserInfo response. The `groups`
scope returns the user's IAM group display names through UserInfo, and LIP maps the highest matching
group to its application role:

| Identity Domain group | Role |
| --- | --- |
| `OCI-LIP-Viewers` | Viewer |
| `OCI-LIP-Operators` | Operator |
| `OCI-LIP-Admins` | Admin |

Create a dedicated active sign-on policy for the LIP application. Its allow rule should use the
domain's intended identity provider and client network scope. Assign only the LIP application to
this policy. Keep authorization in the application's enforced role grants and LIP's backend RBAC
instead of duplicating the same group conditions in the sign-on policy.

Do not rely on an unassigned application's implicit use of the Default Sign-On Policy. Customers
often customize that policy with MFA, network-perimeter, or Keep Me Signed In conditions. If no
rule matches an OIDC authorization request, Identity Domains returns `Sign-on policy denies access`
even when the user has the correct application-role grant. The failed-login OCI Audit event contains
the exact policy evaluation reason and should be the first troubleshooting source.

Enable **Bypass consent** on the LIP OAuth client. Otherwise Identity Domains routes every login
through its built-in consent application, which is evaluated against the domain-wide default sign-on
policy instead of LIP's dedicated policy.

The backend enforces the role on every API route. NGINX uses the same signed session to protect
Grafana and passes a verified identity to Grafana's auth-proxy integration. Prometheus remains
container-internal. Do not treat hidden frontend controls as authorization.

Store the OAuth client secret outside Git and Terraform state. For the initial deployment it can be
placed in the VM's root-owned `.env` file with mode `0600`; the production target is an OCI Vault
secret read by the instance principal.

## Runtime Authentication Configuration

```dotenv
AUTH_ENABLED=true
AUTH_PUBLIC_URL=https://lip.example.com
AUTH_SESSION_SECRET=<at-least-32-random-characters>
AUTH_COOKIE_SECURE=true
AUTH_OIDC_DISCOVERY_URL=https://<identity-domain>/.well-known/openid-configuration
AUTH_OIDC_CLIENT_ID=<confidential-application-client-id>
AUTH_OIDC_CLIENT_SECRET=<confidential-application-client-secret>
AUTH_OIDC_SCOPES="openid profile email approles groups"
AUTH_GROUP_CLAIM=groups
AUTH_VIEWER_GROUPS=["OCI-LIP-Viewers"]
AUTH_OPERATOR_GROUPS=["OCI-LIP-Operators"]
AUTH_ADMIN_GROUPS=["OCI-LIP-Admins"]
```

Apply secret-bearing updates from a mode `0600` fragment instead of placing values in shell
arguments:

```bash
sudo ./deploy/arm64/apply-env-fragment.sh /opt/oci-lip/.env /run/secrets/oci-lip-oidc.env
```

The helper writes a timestamped rollback copy. Remove the fragment and obsolete rollback copies
after validation so only the active root-owned configuration retains the client secret.

Authentication fails closed at startup when it is enabled but any OIDC setting, HTTPS public URL,
secure-cookie setting, or strong session secret is missing.

## Public IP TLS and Automatic Renewal

LIP can use a reserved load-balancer IPv4 address as its only public origin. Let's Encrypt IP
certificates use the `shortlived` profile and are valid for 160 hours, so automatic renewal is
mandatory.

Set these values in the private VM's root-owned `.env`:

```bash
AUTH_PUBLIC_URL=https://<load-balancer-ip>
CORS_ORIGINS=["https://<load-balancer-ip>"]
GRAFANA_ROOT_URL=https://<load-balancer-ip>/grafana/
LETSENCRYPT_EMAIL=<operations-email>
LIP_CERTIFICATE_IP=<load-balancer-ip>
LIP_LOAD_BALANCER_ID=<load-balancer-ocid>
LIP_LOAD_BALANCER_LISTENER_NAME=https
LIP_LOAD_BALANCER_CERTIFICATE_PREFIX=oci_lip_ip
LIP_CERTIFICATE_VERIFY_ENDPOINT=true
```

Port 80 remains open on the load balancer. The frontend serves
`/.well-known/acme-challenge/` directly and redirects all other HTTP requests to the same IP over
HTTPS. Test issuance against staging before requesting the trusted certificate:

```bash
sudo LIP_APP_DIR=/opt/oci-lip ./deploy/arm64/request-ip-certificate.sh --staging
sudo LIP_APP_DIR=/opt/oci-lip ./deploy/arm64/request-ip-certificate.sh
```

Install the persistent renewal timer after trusted issuance:

```bash
sudo LIP_APP_DIR=/opt/oci-lip ./deploy/arm64/install-certificate-renewal.sh
sudo systemctl start oci-lip-certificate-renew.service
sudo systemctl list-timers oci-lip-certificate-renew.timer
```

The timer checks twice daily with a randomized delay. Certbot targets only the production
`LIP_CERTIFICATE_IP` lineage and performs issuance only when that certificate is within its renewal
window. After every successful renewal check, the publisher validates the IP SAN and key, creates a
fingerprint-named Load Balancer certificate bundle, updates the HTTPS listener, and waits for the
public endpoint to serve the matching SHA-256 fingerprint.
If verification times out, it restores the previous listener configuration and deletes the failed
bundle. A failed publication makes the systemd service fail and retry; it cannot be reported as a
successful renewal. Renewal status and expiration are exported through `/metrics/health`.

For a new deployment with no HTTPS listener, the first trusted issuance creates an unattached
bundle and prints its `certificate_name`. Set that value as
`load_balancer_certificate_name` in the secure ARM64 Terraform variables, apply the stack to create
the HTTPS listener, and run `renew-certificate.sh` once to verify the served fingerprint. Terraform
ignores subsequent certificate-name changes on that listener because the renewal service owns
rotation.

The Identity Domain OAuth application must use the IP origin for its redirect and logout URIs:

```text
https://<load-balancer-ip>/api/auth/callback
https://<load-balancer-ip>/
```

Keep the old origin registered until the IP certificate, application environment, login, logout,
Grafana, and callback have all been verified.

## DNS and Certificate Hostname

Use a customer-owned DNS name such as `lip.example.com` for production. A wildcard IP-to-name
service such as `sslip.io` can provide a temporary hostname for bootstrap and demonstration
environments when no managed DNS zone is available. It only resolves the hostname to the encoded
public IP; it does not host or proxy LIP.

Treat that dependency as temporary because the customer does not control the zone. Replacing it
requires updating the DNS record, load-balancer certificate, `AUTH_PUBLIC_URL`, OAuth redirect URI,
post-logout URL, and any verification contract that pins the application origin.

## Cutover Sequence

1. Apply the secure stack without a certificate.
2. Verify cloud-init, all container health checks, and load-balancer backend health.
3. Migrate the PostgreSQL data and uploads from the existing VM.
4. Issue the trusted IP certificate and create the Load Balancer certificate bundle.
5. Configure the Identity Domain OAuth application, LIP groups, and dedicated sign-on policy.
6. Enable authentication in the private VM's `.env`.
7. Apply the Load Balancer certificate name to enable HTTPS; NGINX redirects non-ACME HTTP traffic.
8. Validate Viewer, Operator, and Admin behavior.
9. Pause the old worker, enable the new worker schedule, and verify a complete regional scan.
10. Retain the old VM stopped during rollback observation, then remove its public IP and resources.
