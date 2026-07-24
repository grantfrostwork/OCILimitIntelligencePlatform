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
| Scopes | `openid profile email groups` |
| Client type | Confidential |

Configure the ID token or UserInfo response to include the user's IAM group display names in the
`groups` claim. LIP maps the highest matching group to its application role:

| Identity Domain group | Role |
| --- | --- |
| `OCI-LIP-Viewers` | Viewer |
| `OCI-LIP-Operators` | Operator |
| `OCI-LIP-Admins` | Admin |

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
AUTH_OIDC_SCOPES="openid profile email groups"
AUTH_GROUP_CLAIM=groups
AUTH_VIEWER_GROUPS=["OCI-LIP-Viewers"]
AUTH_OPERATOR_GROUPS=["OCI-LIP-Operators"]
AUTH_ADMIN_GROUPS=["OCI-LIP-Admins"]
```

Authentication fails closed at startup when it is enabled but any OIDC setting, HTTPS public URL,
secure-cookie setting, or strong session secret is missing.

## Cutover Sequence

1. Apply the secure stack without a certificate.
2. Verify cloud-init, all container health checks, and load-balancer backend health.
3. Migrate the PostgreSQL data and uploads from the existing VM.
4. Create the DNS record and trusted OCI Certificates certificate.
5. Configure the Identity Domain OAuth application and LIP groups.
6. Enable authentication in the private VM's `.env`.
7. Apply the certificate OCID to enable HTTPS and the HTTP redirect.
8. Validate Viewer, Operator, and Admin behavior.
9. Pause the old worker, enable the new worker schedule, and verify a complete regional scan.
10. Retain the old VM stopped during rollback observation, then remove its public IP and resources.
