"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, getToken } from "../../lib/api";

const GROUPS = [
  { title: "Identity", fields: [
    ["name", "Name", "text"], ["age", "Age", "number"], ["city", "City", "text"],
    ["dependents", "Dependents", "number"],
    ["tax_regime", "Tax regime", ["old", "new", "unsure"]],
    ["risk_appetite", "Risk appetite", ["low", "med", "high", "unsure"]],
  ]},
  { title: "Income (₹)", fields: [
    ["monthly_take_home", "Take-home / month", "number"],
    ["annual_ctc", "Annual CTC", "number"],
    ["other_income_monthly", "Other income / month", "number"],
  ]},
  { title: "Investments (₹)", fields: [
    ["epf_monthly", "EPF / month (employee)", "number"],
    ["existing_corpus", "Existing corpus", "number"],
  ]},
  { title: "Expenses (₹)", fields: [
    ["fixed_household_monthly", "Household / month", "number"],
    ["emi_total_monthly", "EMIs / month", "number"],
    ["travel_annual", "Travel / year", "number"],
    ["adhoc_monthly", "Ad-hoc / month", "number"],
  ]},
  { title: "Protection (₹)", fields: [
    ["health_insurance_cover", "Health cover", "number"],
    ["term_life_cover", "Term life cover", "number"],
    ["emergency_fund", "Emergency fund", "number"],
  ]},
];

const NUMBER_FIELDS = new Set(
  GROUPS.flatMap((g) => g.fields).filter(([, , t]) => t === "number").map(([k]) => k)
);

function pct(x) { return x == null ? "—" : `${Math.round(x * 100)}%`; }
function money(x) { return x == null ? "—" : `₹${Number(x).toLocaleString("en-IN")}`; }

export default function ProformaEditor({ params }) {
  const router = useRouter();
  const id = params.id;
  const [data, setData] = useState(null);
  const [derived, setDerived] = useState(null);
  const [version, setVersion] = useState(null);
  const [edits, setEdits] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    const p = await api.getProforma(id);
    setData(p.data); setDerived(p.derived); setVersion(p.version); setEdits({});
  }
  useEffect(() => {
    if (!getToken()) { router.replace("/login"); return; }
    load().catch((e) => setError(e.message));
  }, [id, router]);

  function fieldValue(key) {
    if (key in edits) return edits[key];
    return data?.[key]?.value ?? "";
  }
  function setField(key, v) { setEdits((e) => ({ ...e, [key]: v })); }
  function flag(key) {
    const f = data?.[key];
    if (f && f.source === "ai_extracted" && (f.confidence ?? 1) < 0.6) return "low confidence";
    if (f && f.source === "user_edited") return "edited";
    return null;
  }

  async function save() {
    setBusy(true); setError("");
    try {
      const payload = {};
      for (const [k, v] of Object.entries(edits)) {
        payload[k] = NUMBER_FIELDS.has(k) && v !== "" ? Number(v) : v;
      }
      const p = await api.patchProforma(id, payload);
      setData(p.data); setDerived(p.derived); setVersion(p.version); setEdits({});
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function generateReport() {
    setBusy(true); setError("");
    try {
      const { job_id } = await api.requestReport(id);
      router.push(`/report/${job_id}`);
    } catch (e) { setError(e.message); setBusy(false); }
  }

  if (error && !data) return <div className="container error">{error}</div>;
  if (!data) return <div className="container muted">Loading profile…</div>;

  const lists = [
    ["sips", "SIPs"], ["fds", "FDs"], ["other_investments", "Other investments"], ["goals", "Goals"],
  ];

  return (
    <div className="container">
      <h1>Your profile <span className="muted" style={{ fontSize: 14 }}>v{version}</span></h1>

      <div className="card">
        <h2>Snapshot</h2>
        <div className="derived-grid">
          <div className="metric"><div className="v">{pct(derived.savings_rate)}</div><div className="k">Savings rate</div></div>
          <div className="metric"><div className="v">{derived.emergency_fund_months ?? "—"}</div><div className="k">Emergency fund (months)</div></div>
          <div className="metric"><div className="v">{pct(derived.tax_saving_80c_utilization)}</div><div className="k">80C utilization</div></div>
          <div className="metric"><div className="v">{pct(derived.expense_to_income_ratio)}</div><div className="k">Expense / income</div></div>
          <div className="metric"><div className="v">{money(derived.total_monthly_expenses)}</div><div className="k">Monthly expenses</div></div>
          <div className="metric"><div className="v">{money(derived.monthly_investment_outflow)}</div><div className="k">Monthly investing</div></div>
        </div>
      </div>

      {GROUPS.map((g) => (
        <div className="card" key={g.title}>
          <h2>{g.title}</h2>
          <div className="grid">
            {g.fields.map(([key, label, type]) => (
              <div className="field" key={key}>
                <label>{label}{flag(key) && <span className="flag">⚑ {flag(key)}</span>}</label>
                {Array.isArray(type) ? (
                  <select value={fieldValue(key)} onChange={(e) => setField(key, e.target.value)}>
                    <option value="">—</option>
                    {type.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                ) : (
                  <input type={type} value={fieldValue(key)} onChange={(e) => setField(key, e.target.value)} />
                )}
              </div>
            ))}
          </div>
        </div>
      ))}

      <div className="card">
        <h2>Holdings (read-only)</h2>
        {lists.map(([key, label]) => {
          const v = data[key];
          return (
            <div key={key} style={{ marginBottom: 6, fontSize: 14 }}>
              <span className="muted">{label}: </span>
              {v == null ? <span className="muted">not asked</span>
                : v.length === 0 ? <span className="muted">none</span>
                : <span>{JSON.stringify(v)}</span>}
            </div>
          );
        })}
      </div>

      <div className="row">
        <button onClick={save} disabled={busy || Object.keys(edits).length === 0}>
          {busy ? "Saving…" : `Save changes${Object.keys(edits).length ? ` (${Object.keys(edits).length})` : ""}`}
        </button>
        <button className="secondary" onClick={generateReport} disabled={busy}>Generate report →</button>
        {error && <span className="error">{error}</span>}
      </div>
    </div>
  );
}
