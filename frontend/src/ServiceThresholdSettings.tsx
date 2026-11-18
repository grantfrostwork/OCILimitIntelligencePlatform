import { useEffect, useState } from "react";
import { Plus, RotateCcw, Save } from "lucide-react";
import { getServiceThresholds, resetServiceThreshold, saveServiceThreshold } from "./api";
import type { ServiceThreshold, ServiceThresholdSettings as ThresholdSettings } from "./types";

function OverrideRow({ row, busy, onSave, onReset }: {
  row: ServiceThreshold; busy: boolean;
  onSave: (row: ServiceThreshold) => void; onReset: (service: string) => void;
}) {
  const [draft, setDraft] = useState(row);
  useEffect(() => setDraft(row), [row.service_name, row.warning_threshold_percent, row.critical_threshold_percent]);
  const dirty = draft.warning_threshold_percent !== row.warning_threshold_percent || draft.critical_threshold_percent !== row.critical_threshold_percent;
  return <tr>
    <td><strong>{row.service_name}</strong><span className="threshold-source">Service override · all regions</span></td>
    <td><input aria-label={`${row.service_name} warning threshold (%)`} type="number" min="0.1" max="100" step="0.1" required
      value={draft.warning_threshold_percent} onChange={(e) => setDraft({ ...draft, warning_threshold_percent: Number(e.target.value) })} /></td>
    <td><input aria-label={`${row.service_name} critical threshold (%)`} type="number" min={draft.warning_threshold_percent} max="100" step="0.1" required
      value={draft.critical_threshold_percent} onChange={(e) => setDraft({ ...draft, critical_threshold_percent: Number(e.target.value) })} /></td>
    <td><div className="threshold-row-actions">
      <button type="submit" className="button secondary" disabled={busy || !dirty} onClick={(e) => {
        const form = e.currentTarget.form;
        if (form?.reportValidity()) { e.preventDefault(); onSave(draft); }
      }}><Save size={15} /> Save</button>
      <button type="button" className="button secondary" disabled={busy} onClick={() => onReset(row.service_name)}><RotateCcw size={15} /> Reset to default</button>
    </div></td>
  </tr>;
}

export function ServiceThresholdSettings({ revision, onSaved, onOverridesChanged }: { revision: number; onSaved: () => void; onOverridesChanged: (rows: ServiceThreshold[]) => void }) {
  const [settings, setSettings] = useState<ThresholdSettings | null>(null);
  const [service, setService] = useState("");
  const [warning, setWarning] = useState(90);
  const [critical, setCritical] = useState(98);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let active = true;
    getServiceThresholds().then((result) => {
      if (!active) return;
      setSettings(result); onOverridesChanged(result.overrides); setWarning(result.warning_threshold_percent); setCritical(result.critical_threshold_percent);
    }).catch((err) => { if (active) setError(String(err.message ?? err)); });
    return () => { active = false; };
  }, [revision]);

  async function persist(row: ServiceThreshold | string) {
    if (typeof row !== "string" && (row.warning_threshold_percent <= 0 || row.warning_threshold_percent > row.critical_threshold_percent || row.critical_threshold_percent > 100)) {
      setError("Use percentages above 0 and at most 100, with critical at least warning."); return;
    }
    setBusy(true); setError(""); setNotice("");
    try {
      const result = typeof row === "string" ? await resetServiceThreshold(row) : await saveServiceThreshold(row);
      setSettings(result); onOverridesChanged(result.overrides); setService("");
      setWarning(result.warning_threshold_percent); setCritical(result.critical_threshold_percent);
      setNotice(typeof row === "string" ? `${row} now uses the default thresholds.` : `Thresholds saved for ${row.service_name}.`);
      onSaved();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not save service thresholds."); }
    finally { setBusy(false); }
  }
  const available = settings?.available_services.filter((name) => !settings.overrides.some((row) => row.service_name === name)) ?? [];
  return <section className="service-threshold-settings" aria-labelledby="service-threshold-title">
    <h3 id="service-threshold-title">Service overrides</h3>
    <p className="settings-help">Services inherit the default warning and critical thresholds unless you add an override. Each override applies to every limit in that service, across all regions. Saving here does not send email; alerts are evaluated on the next scan.</p>
    {error && <div className="error-banner" role="alert">{error}</div>}
    {notice && <div className="info-banner" role="status">{notice}</div>}
    {!settings ? <p>Loading service thresholds…</p> : <>
      <p className="threshold-defaults">Default warning <strong>{settings.warning_threshold_percent}%</strong> · critical <strong>{settings.critical_threshold_percent}%</strong></p>
      {settings.overrides.length > 0 ? <form onSubmit={(event) => event.preventDefault()}>
        <fieldset disabled={busy}><div className="table-shell"><table className="threshold-table"><thead><tr><th>Service</th><th>Warning (%)</th><th>Critical (%)</th><th>Actions</th></tr></thead>
          <tbody>{settings.overrides.map((row) => <OverrideRow key={row.service_name} row={row} busy={busy} onSave={(value) => void persist(value)} onReset={(value) => void persist(value)} />)}</tbody>
        </table></div></fieldset>
      </form> : <p className="settings-help">No service overrides. All services use the defaults.</p>}
      <form className="threshold-add" onSubmit={(event) => { event.preventDefault(); if (service) void persist({ service_name: service, warning_threshold_percent: warning, critical_threshold_percent: critical }); }}>
        <fieldset disabled={busy || !available.length}><div className="threshold-add-fields">
          <label>Service<select aria-label="Service for threshold override" required value={service} onChange={(event) => setService(event.target.value)}>
            <option value="">Choose a service…</option>{available.map((name) => <option key={name} value={name}>{name}</option>)}
          </select></label>
          <label>Warning (%)<input aria-label="New service warning threshold (%)" type="number" min="0.1" max="100" step="0.1" required value={warning} onChange={(e) => setWarning(Number(e.target.value))} /></label>
          <label>Critical (%)<input aria-label="New service critical threshold (%)" type="number" min={warning} max="100" step="0.1" required value={critical} onChange={(e) => setCritical(Number(e.target.value))} /></label>
          <button type="submit" className="button secondary" disabled={!service || busy}><Plus size={16} /> Add override</button>
        </div></fieldset>
      </form>
      {!settings.available_services.length && <p className="settings-help">Run a scan to discover services before adding an override.</p>}
    </>}
  </section>;
}
