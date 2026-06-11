# IAM Policy Recommendations

Create a dynamic group for the LIP VM instance:

```text
ALL {instance.compartment.id = '<lip-vm-compartment-ocid>'}
```

Start with these policies:

```text
Allow dynamic-group lip-vm-dg to inspect limits in tenancy
Allow dynamic-group lip-vm-dg to inspect compartments in tenancy
Allow dynamic-group lip-vm-dg to inspect tenancies in tenancy
Allow dynamic-group lip-vm-dg to manage ons-topics in compartment <lip-compartment>
Allow dynamic-group lip-vm-dg to manage ons-subscriptions in compartment <lip-compartment>
Allow dynamic-group lip-vm-dg to use ons-topics in compartment <lip-compartment>
```

If the CLI returns authorization errors for region or AD discovery, add:

```text
Allow dynamic-group lip-vm-dg to inspect availability-domains in tenancy
```

Avoid granting broad `manage all-resources` to the production app. The scanner needs read-oriented limit visibility and scoped notification management.
