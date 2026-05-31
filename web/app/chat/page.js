"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import { api, getToken, clearToken } from "../lib/api";

function pctFromCoverage(cov) {
  const keys = Object.keys(cov || {});
  if (!keys.length) return 0;
  const known = keys.filter((k) => cov[k] === "known").length;
  return Math.round((100 * known) / keys.length);
}

export default function Chat() {
  const router = useRouter();
  const [messages, setMessages] = useState([]);
  const [sid, setSid] = useState(null);
  const [coverage, setCoverage] = useState(0);
  const [phase, setPhase] = useState("interviewing");
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const logRef = useRef(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    (async () => {
      try {
        const existing = localStorage.getItem("ff_session");
        if (existing) {
          const s = await api.getSession(existing);
          setSid(existing);
          setMessages(s.transcript || []);
          setCoverage(pctFromCoverage(s.coverage));
          setPhase(s.phase || "interviewing");
        } else {
          const s = await api.startSession();
          localStorage.setItem("ff_session", s.session_id);
          setSid(s.session_id);
          setMessages([{ role: "assistant", content: s.assistant_message }]);
        }
      } catch (err) {
        setError(err.message);
      }
    })();
  }, [router]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [messages]);

  async function send(e) {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: text }]);
    setBusy(true);
    setError("");
    try {
      const r = await api.sendMessage(sid, text);
      setMessages((m) => [...m, { role: "assistant", content: r.assistant_message }]);
      setCoverage(r.coverage_pct);
      setPhase(r.phase);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function build() {
    setBusy(true);
    try {
      const { proforma_id } = await api.buildProforma(sid);
      router.push(`/proforma/${proforma_id}`);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  function startOver() {
    localStorage.removeItem("ff_session");
    window.location.reload();
  }
  function logout() {
    clearToken();
    localStorage.removeItem("ff_session");
    router.replace("/login");
  }

  return (
    <div className="container">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1>Let’s map your finances</h1>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="secondary" onClick={startOver}>Start over</button>
          <button className="secondary" onClick={logout}>Log out</button>
        </div>
      </div>

      <div className="card">
        <label>Profile completeness</label>
        <div className="progress"><div style={{ width: `${coverage}%` }} /></div>
        <div className="muted" style={{ fontSize: 12 }}>{coverage}% — {phase}</div>
      </div>

      <div className="card">
        <div className="chat-log" ref={logRef} style={{ maxHeight: 420, overflowY: "auto" }}>
          {messages.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              {m.role === "assistant" ? <ReactMarkdown>{m.content}</ReactMarkdown> : m.content}
            </div>
          ))}
        </div>

        {phase === "confirming" ? (
          <button onClick={build} disabled={busy}>Build my profile →</button>
        ) : (
          <form className="chat-input" onSubmit={send}>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Type your answer…"
              disabled={busy || !sid}
            />
            <button type="submit" disabled={busy || !sid}>{busy ? "…" : "Send"}</button>
          </form>
        )}
        {error && <div className="error">{error}</div>}
        {phase === "confirming" && (
          <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
            You can also keep chatting to add or correct details.
          </div>
        )}
      </div>
    </div>
  );
}
