import { useEffect, useMemo, useState } from "react";

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || res.statusText || "Request failed");
  }
  return res.json();
}

export default function App() {
  const [nodes, setNodes] = useState([]);
  const [cluster, setCluster] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [events, setEvents] = useState([]);
  const [providers, setProviders] = useState({ active: "", providers: [] });
  const [provisionServers, setProvisionServers] = useState({ provider: "", servers: [] });
  const [jobs, setJobs] = useState([]);
  const [jobDetail, setJobDetail] = useState(null);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [selectedJobId, setSelectedJobId] = useState("");
  const [showEnabledOnly, setShowEnabledOnly] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [newTask, setNewTask] = useState({
    profile_id: "",
    authorized_target: "internal test app",
    task_type: "open_url",
    url: "",
    timeout_seconds: 300,
    max_retries: 1
  });

  const totals = useMemo(() => {
    const online = nodes.filter((n) => n.status === "online").length;
    const stale = nodes.filter((n) => n.status === "stale").length;
    return { online, stale, total: nodes.length };
  }, [nodes]);

  const visibleProvisionServers = useMemo(() => {
    const servers = provisionServers.servers || [];
    if (!showEnabledOnly) return servers;
    return servers.filter((s) => s.enabled);
  }, [provisionServers, showEnabledOnly]);

  const refreshCore = async () => {
    setLoading(true);
    try {
      const [nextNodes, nextCluster, nextTasks, nextProviders, nextJobs, nextServers] = await Promise.all([
        api("/api/master/nodes"),
        api("/api/master/cluster/status"),
        api("/api/master/tasks"),
        api("/api/master/providers"),
        api("/api/master/provision/jobs"),
        api("/api/master/provision/servers")
      ]);
      setNodes(nextNodes);
      setCluster(nextCluster);
      setTasks(nextTasks);
      setProviders(nextProviders);
      setJobs(nextJobs);
      setProvisionServers(nextServers);
      if (!selectedTaskId && nextTasks[0]) setSelectedTaskId(nextTasks[0].id);
      if (!selectedJobId && nextJobs[0]) setSelectedJobId(nextJobs[0].id);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refreshCore();
    const timer = window.setInterval(refreshCore, 4000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!selectedTaskId) return;
    api(`/api/master/tasks/${selectedTaskId}/events`).then(setEvents).catch(() => setEvents([]));
  }, [selectedTaskId]);

  useEffect(() => {
    if (!selectedJobId) return;
    api(`/api/master/provision/jobs/${selectedJobId}`).then(setJobDetail).catch(() => setJobDetail(null));
  }, [selectedJobId]);

  const createTask = async () => {
    const payload = {
      profile_id: newTask.profile_id || null,
      authorized_target: newTask.authorized_target,
      task_type: newTask.task_type,
      url: newTask.task_type === "open_url" ? (newTask.url.trim() || null) : null,
      timeout_seconds: Number(newTask.timeout_seconds) || 300,
      max_retries: Number(newTask.max_retries) || 1
    };
    await api("/api/master/tasks", { method: "POST", body: JSON.stringify(payload) });
    await refreshCore();
  };

  const runProvision = async (dryRun) => {
    const result = await api("/api/master/provision/run", {
      method: "POST",
      body: JSON.stringify({ dry_run: dryRun })
    });
    const nextJobId = result?.job?.id;
    if (nextJobId) {
      setSelectedJobId(nextJobId);
      setJobDetail(result);
    }
    await refreshCore();
  };

  const setProvider = async (provider) => {
    await api("/api/master/providers/active", {
      method: "PUT",
      body: JSON.stringify({ provider })
    });
    await refreshCore();
  };

  return (
    <div className="page">
      <header className="topbar">
        <div>
          <h1>Master Console</h1>
          <p>独立 Master 控制台（不复用 Worker 前端）</p>
        </div>
        <button onClick={refreshCore} disabled={loading}>{loading ? "Refreshing..." : "Refresh"}</button>
      </header>

      {error && <div className="error">{error}</div>}

      <section className="cards">
        <div className="card"><span>Nodes</span><strong>{totals.total}</strong></div>
        <div className="card"><span>Online</span><strong>{totals.online}</strong></div>
        <div className="card"><span>Stale</span><strong>{totals.stale}</strong></div>
        <div className="card"><span>Queued</span><strong>{cluster?.tasks?.queued ?? 0}</strong></div>
      </section>

      <section className="grid two">
        <div className="panel">
          <h2>Providers</h2>
          <p>Active: <b>{providers.active || "-"}</b></p>
          <div className="row wrap">
            {providers.providers?.map((name) => (
              <button key={name} onClick={() => setProvider(name)}>{name}</button>
            ))}
          </div>
        </div>

        <div className="panel">
          <h2>Provision</h2>
          <p>Provider: <b>{provisionServers.provider || providers.active || "-"}</b></p>
          <p>Servers: <b>{provisionServers.servers?.length || 0}</b></p>
          <div className="row">
            <button onClick={() => runProvision(true)}>Run Dry-Run</button>
            <button className="warn" onClick={() => runProvision(false)}>Run Deploy</button>
          </div>
        </div>
      </section>

      <section className="grid two">
        <div className="panel">
          <h2>Nodes</h2>
          <table>
            <thead><tr><th>Node</th><th>Status</th><th>Load</th><th>Mem</th></tr></thead>
            <tbody>
              {nodes.map((n) => (
                <tr key={n.node_id}>
                  <td>{n.node_id}</td>
                  <td>{n.status}</td>
                  <td>{n.running_profiles}/{n.max_profiles}</td>
                  <td>{n.mem_used_mb || 0}/{n.mem_total_mb || 0} MB</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel">
          <h2>Create Master Task</h2>
          <div className="form">
            <input value={newTask.profile_id} onChange={(e) => setNewTask({ ...newTask, profile_id: e.target.value })} placeholder="profile_id (optional)" />
            <input value={newTask.authorized_target} onChange={(e) => setNewTask({ ...newTask, authorized_target: e.target.value })} placeholder="authorized_target" />
            <select value={newTask.task_type} onChange={(e) => setNewTask({ ...newTask, task_type: e.target.value })}>
              <option value="open_url">open_url</option>
              <option value="external_cdp">external_cdp</option>
            </select>
            <input value={newTask.url} onChange={(e) => setNewTask({ ...newTask, url: e.target.value })} placeholder="url (open_url only)" />
            <div className="row">
              <input type="number" value={newTask.timeout_seconds} onChange={(e) => setNewTask({ ...newTask, timeout_seconds: e.target.value })} placeholder="timeout" />
              <input type="number" value={newTask.max_retries} onChange={(e) => setNewTask({ ...newTask, max_retries: e.target.value })} placeholder="max_retries" />
            </div>
            <button onClick={createTask}>Create Task</button>
          </div>
        </div>
      </section>

      <section className="grid two">
        <div className="panel">
          <h2>Provision Servers</h2>
          <div className="row between">
            <p>Showing: <b>{visibleProvisionServers.length}</b> / {provisionServers.servers?.length || 0}</p>
            <label className="checkbox">
              <input type="checkbox" checked={showEnabledOnly} onChange={(e) => setShowEnabledOnly(e.target.checked)} />
              enabled only
            </label>
          </div>
          <table>
            <thead><tr><th>Node</th><th>Host</th><th>User</th><th>Status</th></tr></thead>
            <tbody>
              {visibleProvisionServers.map((s) => (
                <tr key={s.node_id}>
                  <td>{s.node_id}</td>
                  <td>{s.host}:{s.port}</td>
                  <td>{s.username}</td>
                  <td>{s.enabled ? "enabled" : "disabled"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel">
          <h2>Master Tasks</h2>
          <select value={selectedTaskId} onChange={(e) => setSelectedTaskId(e.target.value)}>
            <option value="">Select task</option>
            {tasks.map((t) => (
              <option key={t.id} value={t.id}>{t.id.slice(0, 8)} | {t.status} | {t.target_node_id || "unassigned"}</option>
            ))}
          </select>
          <div className="list">
            {events.map((ev) => (
              <div key={ev.id} className="item">
                <b>{ev.event_type}</b>
                <span>{ev.node_id || "-"}</span>
                <p>{ev.message || ""}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="panel">
          <h2>Provision Jobs</h2>
          <select value={selectedJobId} onChange={(e) => setSelectedJobId(e.target.value)}>
            <option value="">Select job</option>
            {jobs.map((j) => (
              <option key={j.id} value={j.id}>{j.id.slice(0, 8)} | {j.status}</option>
            ))}
          </select>
          <div className="list">
            {jobDetail?.items?.map((it) => (
              <div key={it.id} className="item">
                <b>{it.node_id}</b>
                <span>{it.status}</span>
                <p>{it.message || ""}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
