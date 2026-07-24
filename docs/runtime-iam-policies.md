# OCI LIP Runtime IAM Policies

This document records the OCI permissions required by the OCI Limit Intelligence Platform
runtime. It deliberately separates the VM's instance-principal permissions from the permissions
needed by a person or Resource Manager stack that deploys the infrastructure.

## Current Tenancy State

Live validation on July 24, 2026 found that every instance in the tenancy root is included in
`InstancePrincipalGroup`:

```text
Any {Any {instance.compartment.id = '<tenancy-ocid>'}}
```

The active `InstancePrincipalPolicy` currently grants:

```text
Allow dynamic-group InstancePrincipalGroup to manage all-resources in tenancy
```

This is the broad access that currently allows the ARM LIP VM to run. It is materially wider than
the application requires and also applies to unrelated root-compartment instances. Leave it in
place during the network migration, then replace it using the policy reduction procedure below.
No IAM policy is changed by the secure network deployment stack.

## Runtime Dynamic Group

For a single VM, use the instance OCID so that no other instance inherits the application's
tenancy-wide read permissions:

```text
instance.id = '<lip-vm-instance-ocid>'
```

For replaceable instances, use an isolated compartment and a protected defined tag:

```text
ALL {
  instance.compartment.id = '<lip-compartment-ocid>',
  tag.OCI-LIP.Role.value = 'runtime'
}
```

Only deployment administrators should be able to apply the `OCI-LIP.Role=runtime` tag.

## Required Scanner Policy

The web application currently calls:

- `IdentityClient.list_region_subscriptions`
- `LimitsClient.list_services`
- `LimitsClient.list_limit_definitions`
- `LimitsClient.list_limit_values`
- `LimitsClient.get_resource_availability`

The minimum runtime policy for those operations is:

```text
Allow dynamic-group lip-runtime to inspect tenancies in tenancy
Allow dynamic-group lip-runtime to read resource-availability in tenancy
```

`inspect tenancies` permits subscribed-region discovery. `read resource-availability` includes the
inspect operations required for services, limit definitions, and limit values, plus the read
permission required for resource availability.

The scanner does not require permissions to manage Compute, networking, compartments, databases,
quotas, limit-increase requests, or `all-resources`.

## Optional Notifications Policy

No Notifications permissions are required when `LIP_ENABLE_NOTIFICATIONS=false`.

The current self-provisioning workflow lists and creates topics and email subscriptions, then
publishes messages. Scope those operations to the dedicated LIP compartment:

```text
Allow dynamic-group lip-runtime to manage ons-topics in compartment OCI-LIP
Allow dynamic-group lip-runtime to inspect ons-subscriptions in compartment OCI-LIP
```

For a more restrictive deployment, provision the topic and subscriptions with Terraform and change
the runtime workflow so it only validates configuration and publishes:

```text
Allow dynamic-group lip-runtime to inspect ons-topics in compartment OCI-LIP
Allow dynamic-group lip-runtime to inspect ons-subscriptions in compartment OCI-LIP
Allow dynamic-group lip-runtime to use ons-topics in compartment OCI-LIP
  where request.operation = 'PublishMessage'
```

Always set `LIP_NOTIFICATION_COMPARTMENT_OCID` to the dedicated application compartment. Do not
allow the notification configuration to fall back to the tenancy root in production.

## Optional Vault Policy

Instance-principal authentication does not require a stored credential. If OCI Vault is later used
for the OIDC client secret, database password, or Grafana administrator password, keep only LIP
secrets in the application compartment and grant:

```text
Allow dynamic-group lip-runtime to read secret-bundles in compartment OCI-LIP
```

No Vault permission is required until the application retrieves those secrets directly.

## Application User Groups

These IAM Identity Domain groups authorize people to use LIP; they do not grant OCI API permissions:

| Group | LIP role | Application permissions |
| --- | --- | --- |
| `OCI-LIP-Viewers` | Viewer | Dashboard, limits, alerts, trends, Grafana, and exports |
| `OCI-LIP-Operators` | Operator | Viewer access plus scans, BOM analysis, mute/unmute, and alert resolution |
| `OCI-LIP-Admins` | Admin | Operator access plus region allowlist, scan schedule, and notification configuration |

Assign and remove users through IAM group membership. The FastAPI backend must enforce these roles;
frontend control visibility is only a usability feature.

## Deployment-Time Permissions

The identity performing deployment may need to create or manage compartments, VCN resources,
subnets, gateways, NSGs, load balancers, certificates, DNS records, Bastion resources, instances,
dynamic groups, and policies. Those deployment permissions belong to a human deployment group or
Resource Manager stack principal. They must never be granted to the LIP runtime dynamic group.

For customers with strict separation of duties, split deployment into:

1. A security bootstrap run that creates the dynamic group and root-level policy.
2. A workload stack that creates resources only inside the dedicated LIP compartment.

## Policy Reduction Procedure

1. Create the narrow runtime dynamic group and policies alongside the existing broad policy.
2. Run subscribed-region discovery.
3. Complete two full scans across all selected regions.
4. Test BOM analysis against persisted scan data.
5. If enabled, validate topic discovery, subscription state, and message publication separately.
6. Review OCI Audit events and application logs for authorization failures.
7. Remove the VM's `manage all-resources` or Administrator access.
8. Repeat a full scan after policy removal and retain the rollback policy until validation completes.

## References

- [OCI Service Limits IAM requirements](https://docs.oracle.com/en-us/iaas/Content/General/service-limits/overview.htm)
- [OCI IAM operation permissions](https://docs.oracle.com/en-us/iaas/Content/Identity/policyreference/iampolicyreference.htm)
- [OCI Notifications policy reference](https://docs.oracle.com/en-us/iaas/Content/Identity/policyreference/notificationpolicyreference.htm)
- [OCI dynamic groups](https://docs.oracle.com/en-us/iaas/Content/Identity/Tasks/managingdynamicgroups.htm)
- [OCI Vault policy reference](https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/keypolicyreference.htm)
