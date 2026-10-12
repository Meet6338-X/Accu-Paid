import React, { useCallback, useEffect, useRef, useState } from 'react';
import Chat from './Chat.jsx';
import Runs from './Runs.jsx';
import Ingest from './Ingest.jsx';
import Health from './Health.jsx';
import { api } from './api.js';

const TABS = [
  { id: 'chat', label: 'Chat' },
  { id: 'runs', label: 'Runs' },
  { id: 'ingest', label: 'Ingest' },
  { id: 'health', label: 'Health' },
];

function loadHistory() {
  try { return JSON.parse(localStorage.getItem('accupaid.runs') || '[]'); }
  catch { return []; }
}

export default function App() {
  const [tab, setTab] = useState('chat');
  const [health, setHealth] = useState(null);
  const [history, setHistory] = useState(loadHistory);
  const [jumpRun, setJumpRun] = useState(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ status: 'down' }));
  }, []);

  const remember = useCallback((runId, label) => {
    setHistory((h) => {
      const next = [{ runId, label, at: Date.now() }, ...h.filter((x) => x.runId !== runId)].slice(0, 20);
      try { localStorage.setItem('accupaid.runs', JSON.stringify(next)); } catch {}
      return next;
    });
  }, []);

  const openRun = (runId) => { setJumpRun({ runId, n: Date.now() }); setTab('runs'); };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo-mark" aria-hidden="true">A</span>
          <div>
            <strong>AccuPaid Console</strong>
            <span className="sub">approval-gated payroll agent</span>
          </div>
        </div>
        <div className="top-right">
          <span className={`pill ${health && health.status === 'ok' ? 'ok' : 'bad'}`} role="status">
            {health ? (health.status === 'ok' ? 'API live' : 'API down') : 'checking…'}
          </span>
          <nav className="tabs" aria-label="Views">
            {TABS.map((t) => (
              <button key={t.id} className={tab === t.id ? 'on' : ''} onClick={() => setTab(t.id)}
                aria-pressed={tab === t.id}>{t.label}</button>
            ))}
          </nav>
        </div>
      </header>

      <div className="layout">
        {history.length > 0 && (
        <aside className="history" aria-label="Recent runs">
          <h2>Recent runs</h2>
          <ul>
            {history.map((h) => (
              <li key={h.runId}>
                <button onClick={() => openRun(h.runId)} title={h.runId}>
                  <code>{h.runId}</code>
                  <span className="muted">{h.label}</span>
                </button>
              </li>
            ))}
          </ul>
        </aside>
        )}

        <main className="view">
          {tab === 'chat' && <Chat remember={remember} />}
          {tab === 'runs' && <Runs jumpRun={jumpRun} />}
          {tab === 'ingest' && <Ingest />}
          {tab === 'health' && <Health health={health} />}
        </main>
      </div>
    </div>
  );
}
