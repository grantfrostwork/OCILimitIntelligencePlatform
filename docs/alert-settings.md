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

## Service-specific thresholds

Under **Email alert settings → Service overrides**, choose a scanned OCI service and enter its warning and critical percentages. Click **Add override**. An override applies to every limit in that service, across all monitored regions. Services without an override inherit the default thresholds shown above the table.

Edit an existing row and click **Save**, or click **Reset to default** to remove that service's override. Changing the global defaults does not change explicit service overrides. Thresholds must be above 0 and at most 100, with critical at least warning. At exactly the configured percentage, the corresponding warning/critical level applies.

The limit matrix shows each row's effective warning/critical pair and whether it comes from a service override or the defaults. Dashboard counts, filters, CSV classification, forecasts and email `{threshold}` values use the same policy. Prometheus/Grafana receive a best-effort metric refresh after settings changes and on subsequent completed scans.

Saving thresholds does not itself send an email. The next scan evaluates delivery using the new settings. Existing mute settings and the six-hour per-limit/per-severity deduplication window still apply. Raising a threshold closes an open threshold alert that no longer matches the latest recorded utilization/severity; historical delivery events are retained. Forecasts are recalculated using stored history.

Administrators can view and modify overrides. The API is `GET /api/service-thresholds`, `PUT /api/service-thresholds/{service_name}` with `warning_threshold_percent` and `critical_threshold_percent`, and `DELETE /api/service-thresholds/{service_name}` to inherit defaults again. Changes are recorded in the audit log. Overrides are stored in the additive `service_alert_thresholds` table; no environment-file edits or restarts are required to tune them.
