"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, getToken } from "../../lib/api";

export default function ReportViewer({ params }) {
  const router = useRouter();
  const jobId = params.jobId;
  const [status, setStatus] = useState("pending");
  const [content, setContent] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getToken()) { router.replace("/login"); return; }
    let active = true;
    let timer;
    async function poll() {
      try {
        const v = await api.getReport(jobId);
        if (!active) return;
        setStatus(v.status);
        if (v.status === "done") { setContent(v.content); return; }
        if (v.status === "failed") { setError(v.error || "report generation failed"); return; }
        timer = setTimeout(poll, 3000);
      } catch (e) {
        if (active) setError(e.message);
      }
    }
    poll();
    return () => { active = false; clearTimeout(timer); };
  }, [jobId, router]);

  if (error) return <div className="container error">Report error: {error}</div>;

  if (status !== "done" || !content) {
    return (
      <div className="container">
        <h1>Generating your report…</h1>
        <div className="card spinner">
          Analyzing your profile against financial principles and citing sources. This can take up to ~2 minutes.
          <div className="progress" style={{ marginTop: 12 }}><div style={{ width: "40%" }} /></div>
          <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>status: {status}</div>
        </div>
      </div>
    );
  }

  const c = content;
  return (
    <div className="container">
      <h1>Your preliminary report</h1>

      {c.snapshot && (
        <div className="card">
          <h2>Snapshot</h2>
          <div className="derived-grid">
            {Object.entries(c.snapshot).map(([k, v]) => (
              <div className="metric" key={k}>
                <div className="v">{typeof v === "object" ? JSON.stringify(v) : String(v)}</div>
                <div className="k">{k.replace(/_/g, " ")}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card">
        <h2>Ratings</h2>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
          {(c.ratings || []).map((r, i) => (
            <span key={i} className={`chip ${r.rating}`}>
              {r.dimension.replace(/_/g, " ")}: {r.rating} {r.value != null && `(${r.value})`}
            </span>
          ))}
        </div>
      </div>

      {c.findings?.length > 0 && (
        <div className="card">
          <h2>What we see</h2>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {c.findings.map((f, i) => <li key={i} style={{ marginBottom: 6 }}>{f}</li>)}
          </ul>
        </div>
      )}

      <div className="card">
        <h2>Recommendations</h2>
        {(c.recommendations || []).map((r, i) => (
          <div className="rec" key={i}>
            <div className="pri">{r.priority} priority</div>
            <div style={{ fontWeight: 600 }}>{r.action}</div>
            <div style={{ fontSize: 14, marginTop: 4 }}>{r.rationale}</div>
            {r.sources?.length > 0 && (
              <div className="sources">
                Source{r.sources.length > 1 ? "s" : ""}:{" "}
                {r.sources.map((s, j) => (
                  <span key={j}>
                    {j > 0 && " · "}
                    <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a>
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {c.disclaimer && <div className="card disclaimer">{c.disclaimer}</div>}
    </div>
  );
}
