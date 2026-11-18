import { useEffect, useState } from "react";
import { Bell, Plus, RefreshCw, Save, X } from "lucide-react";
import { getNotificationSettings, saveNotificationSettings, syncNotificationSettings } from "./api";
import type { NotificationSettings } from "./types";

const placeholders = ["service", "limit", "region", "percent_used", "used", "allowed_limit", "severity", "threshold", "message", "app_url"];

export function AlertSettings({ onSaved }: { onSaved: () => void }) {
  const [settings, setSettings] = useState<NotificationSettings | null>(null);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    getNotificationSettings().then(setSettings).catch((err) => setError(String(err.message ?? err)));
  }, []);

  function update(patch: Partial<NotificationSettings>) {
    setSettings((current) => current ? { ...current, ...patch } : current);
    setDirty(true);
    setNotice("");
  }

  function addEmail() {
    const value = email.trim().toLowerCase();
    if (!/^[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+$/.test(value)) {
      setError("Enter a valid email address."); return;
    }
    if (settings && !settings.emails.includes(value)) update({ emails: [...settings.emails, value] });
    setEmail(""); setError("");
  }

  async function persist(sync = false) {
    if (!settings) return;
    if (!sync && email.trim()) { setError("Use Add to include the email address before saving."); return; }
    setBusy(true); setError(""); setNotice("");
    try {
      const result = sync ? await syncNotificationSettings() : await saveNotificationSettings(settings);
      setSettings(result); setDirty(false);
      if (result.last_error) setError(`Settings saved, but delivery setup needs attention: ${result.last_error}`);
      else setNotice(sync ? "Subscription status refreshed." : "Alert settings saved. New recipients must confirm their subscription by email.");
      onSaved();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not save alert settings."); }
    finally { setBusy(false); }
  }

  const values: Record<string, string> = {
    service: "compute", limit: "standard-a1-core-count", region: "us-ashburn-1",
    percent_used: "95.0", used: "19", allowed_limit: "20", severity: 95 >= (settings?.critical_threshold_percent ?? 98) ? "CRITICAL" : "WARNING",
    threshold: String(95 >= (settings?.critical_threshold_percent ?? 98) ? settings?.critical_threshold_percent : settings?.warning_threshold_percent ?? 90),
    message: "standard-a1-core-count in us-ashburn-1 is 95.0% used (19 of 20).",
    app_url: window.location.origin,
  };
  function preview(template: string) {
    return template.replace(/\{\{|\}\}|\{([^{}]+)\}/g, (match, key: string | undefined) => {
      if (match === "{{") return "{";
      if (match === "}}") return "}";
      return key && key in values ? values[key] : match;
    });
  }

  return <section className="panel alert-settings" aria-labelledby="alert-settings-title">
    <div className="panel-header">
      <div><h2 id="alert-settings-title"><Bell size={20} /> Email alert settings</h2>
        <p>Choose when to request a limit increase, who receives the alert, and what it says.</p></div>
      {dirty && <span className="badge">Unsaved changes</span>}
    </div>
    {error && <div className="error-banner" role="alert">{error}</div>}
    {notice && <div className="info-banner" role="status">{notice}</div>}
    {!settings ? <p>Loading alert settings…</p> : <form onSubmit={(event) => { event.preventDefault(); void persist(); }}>
      <fieldset disabled={busy}>
        <label className="notification-toggle"><input type="checkbox" checked={settings.enabled}
          onChange={(event) => update({ enabled: event.target.checked })} /> Enable email alerts</label>
        <p className="settings-help">Alerts are evaluated after each scan of enabled regions. Muted limits are excluded. Repeated alerts for the same limit and severity are limited to once every six hours.</p>
        <div className="settings-columns">
          <div>
            <div className="threshold-fields">
              <label>Warning threshold (%)<input aria-label="Warning threshold (%)" type="number" min="0.1" max="100" step="0.1" required
                value={settings.warning_threshold_percent} onChange={(event) => update({ warning_threshold_percent: Number(event.target.value) })} /></label>
              <label>Critical threshold (%)<input aria-label="Critical threshold (%)" type="number" min={settings.warning_threshold_percent} max="100" step="0.1" required
                value={settings.critical_threshold_percent} onChange={(event) => update({ critical_threshold_percent: Number(event.target.value) })} /></label>
            </div>
            <h3>Email recipients</h3>
            <p className="settings-help">Each new recipient must click the confirmation link sent by OCI Notifications. Removing a recipient revokes their subscription when you save.</p>
            <div className="recipient-add"><input aria-label="New recipient email" type="email" placeholder="name@example.com" value={email}
              onChange={(event) => setEmail(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addEmail(); } }} />
              <button className="button secondary" type="button" onClick={addEmail}><Plus size={16} /> Add</button></div>
            <ul className="recipient-list">{settings.emails.map((recipient) => <li key={recipient}>
              <span>{recipient}</span><span className={`subscription-status ${settings.subscription_status?.[recipient] === "ACTIVE" ? "active" : "pending"}`}>
                {settings.subscription_status?.[recipient] === "ACTIVE" ? "Confirmed" : settings.subscription_status?.[recipient] === "PENDING" ? "Awaiting confirmation" : "Not subscribed"}</span>
              <button className="button secondary" type="button" aria-label={`Remove ${recipient}`} onClick={() => update({ emails: settings.emails.filter((item) => item !== recipient) })}><X size={16} /></button>
            </li>)}</ul>
            {!settings.emails.length && <p className="settings-help">No recipients added.</p>}
            <button className="button secondary" type="button" disabled={dirty || busy} onClick={() => void persist(true)}><RefreshCw size={16} /> Refresh subscription status</button>
          </div>
          <div>
            <label>Email subject<input required maxLength={255} value={settings.subject_template}
              onChange={(event) => update({ subject_template: event.target.value })} /></label>
            <label>Email message<textarea required rows={7} maxLength={10000} value={settings.message_template}
              onChange={(event) => update({ message_template: event.target.value })} /></label>
            <p className="settings-help">Available placeholders: {placeholders.map((key) => <code key={key}>{`{${key}} `}</code>)}</p>
            <div className="email-preview"><h3>Message preview <small>Example data</small></h3>
              <strong>{preview(settings.subject_template)}</strong><pre>{preview(settings.message_template)}</pre></div>
          </div>
        </div>
        {settings.last_error && !error && <div className="error-banner" role="alert">Delivery setup error: {settings.last_error}</div>}
        <div className="settings-footer"><button type="submit" className="button primary" disabled={!dirty || busy}><Save size={16} />{busy ? "Saving…" : "Save alert settings"}</button>
          <span>Threshold changes apply to the dashboard immediately and to alert emails from the next scan.</span></div>
      </fieldset>
    </form>}
  </section>;
}
