# Email alert settings

Sign in as an application Admin and choose **Alert settings** in the top toolbar.

- Choose warning and critical utilization percentages. Critical must be at least warning; both must be greater than zero and no more than 100.
- Add or remove email recipients and choose **Save alert settings**. Each new recipient must confirm OCI Notifications' email. Removed recipients have their subscription deleted on save. Confirmation status can be refreshed in the panel.
- Edit the email subject and message. The preview uses example data. Supported placeholders are `{service}`, `{limit}`, `{region}`, `{percent_used}`, `{used}`, `{allowed_limit}`, `{severity}`, `{threshold}`, `{message}`, and `{app_url}`. The threshold placeholder uses the warning or critical threshold according to the alert's severity.
- Enable or disable email delivery without changing the scan schedule. A recipient list is required to enable delivery.

Settings persist in PostgreSQL. Thresholds apply to current dashboard classification immediately and to collection, trend calculations, and email evaluation on the next scan. Only enabled regions are scanned; a tenancy's subscribed regions are not automatically all enabled. The ringing bell means alerts are enabled; a struck-through bell means the limit is muted. Muted limits do not send utilization emails. The worker checks the saved mute flag during evaluation and again immediately before publication, including when a scan cached the limit before it was muted. Repeated emails are suppressed for six hours per limit and severity; critical escalation can send immediately. Collection failures and limit-value changes remain in the dashboard and do not use the limit-increase email template.

The API supports admin-only GET/PUT `/api/notifications` and POST `/api/notifications/ensure`. Validation rejects malformed addresses, unknown placeholders, invalid thresholds, and blank templates. A cloud synchronization failure is reported in `last_error`; saving settings is independent of successful subscription reconciliation. Retrying synchronization is safe.

Bootstrap a dedicated OCI Notifications topic in the deployment compartment with a unique name. Set `LIP_NOTIFICATION_TOPIC_NAME` and `LIP_NOTIFICATION_COMPARTMENT_OCID` for both API and worker. Set `AUTH_PUBLIC_URL` for both services so worker-generated emails contain the public dashboard URL. The runtime needs `use ons-topics` and `inspect ons-subscriptions` in that dedicated compartment. Topic creation remains a deployment administrator operation.

The BOM analyzer UI, upload endpoints, parsing service, and model/schema mappings have been removed. Historical database tables and deployment backups are retained for rollback and are inaccessible through the application.
