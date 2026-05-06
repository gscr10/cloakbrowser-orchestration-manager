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
  const [token, setToken] = useState(() => window.localStorage.getItem("master_token") || "");
  const [nodes, setNodes] = useState([]);
  const [cluster, setCluster] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [events, setEvents] = useState([]);
  const [providers, setProviders] = useState({ active: "", providers: [] });
  const [provisionServers, setProvisionServers] = useState({ provider: "", servers: [] });
  const [architectureSummary, setArchitectureSummary] = useState(null);
  const [infraWorkers, setInfraWorkers] = useState([]);
  const [infraCapabilities, setInfraCapabilities] = useState([]);
  const [infraProfiles, setInfraProfiles] = useState([]);
  const [bizJobs, setBizJobs] = useState([]);
  const [bizRuns, setBizRuns] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [jobDetail, setJobDetail] = useState(null);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [selectedJobId, setSelectedJobId] = useState("");
  const [showEnabledOnly, setShowEnabledOnly] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [taskDetail, setTaskDetail] = useState(null);
  const [feishuCheck, setFeishuCheck] = useState(null);

  const authedApi = async (path, options = {}) => {
    const nextHeaders = { ...(options.headers || {}) };
    if (token.trim()) {
      nextHeaders.Authorization = `Bearer ${token.trim()}`;
    }
    return api(path, { ...options, headers: nextHeaders });
  };

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
    const offline = nodes.filter((n) => n.status === "offline").length;
    const queued = cluster?.tasks?.queued ?? 0;
    const dispatched = cluster?.tasks?.dispatched ?? 0;
    const running = cluster?.tasks?.running ?? 0;
    return { online, stale, offline, queued, dispatched, running, total: nodes.length };
  }, [nodes]);

  const taskStats = useMemo(() => {
    return {
      success: tasks.filter((t) => t.status === "success").length,
      failed: tasks.filter((t) => t.status === "failed").length,
      running: tasks.filter((t) => t.status === "running").length
    };
  }, [tasks]);

  const visibleProvisionServers = useMemo(() => {
    const servers = provisionServers.servers || [];
    if (!showEnabledOnly) return servers;
    return servers.filter((s) => s.enabled);
  }, [provisionServers, showEnabledOnly]);

  const refreshCore = async () => {
    setLoading(true);
    try {
      const [
        nextNodes,
        nextCluster,
        nextTasks,
        nextProviders,
        nextJobs,
        nextServers,
        nextArchitecture,
        nextInfraWorkers,
        nextInfraCapabilities,
        nextInfraProfiles,
        nextBizJobs,
        nextBizRuns
      ] = await Promise.all([
        authedApi("/api/master/nodes"),
        authedApi("/api/master/cluster/status"),
        authedApi("/api/master/tasks"),
        authedApi("/api/master/providers"),
        authedApi("/api/master/provision/jobs"),
        authedApi("/api/master/provision/servers"),
        authedApi("/api/master/architecture/summary"),
        authedApi("/api/master/infra/workers"),
        authedApi("/api/master/infra/capabilities"),
        authedApi("/api/master/infra/profiles"),
        authedApi("/api/master/biz/jobs"),
        authedApi("/api/master/biz/runs")
      ]);
      setNodes(nextNodes);
      setCluster(nextCluster);
      setTasks(nextTasks);
      setProviders(nextProviders);
      setJobs(nextJobs);
      setProvisionServers(nextServers);
      setArchitectureSummary(nextArchitecture);
      setInfraWorkers(nextInfraWorkers);
      setInfraCapabilities(nextInfraCapabilities);
      setInfraProfiles(nextInfraProfiles);
      setBizJobs(nextBizJobs);
      setBizRuns(nextBizRuns);
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
    Promise.all([
      authedApi(`/api/master/tasks/${selectedTaskId}/events`),
      authedApi(`/api/master/tasks/${selectedTaskId}`)
    ]).then(([nextEvents, nextTask]) => {
      setEvents(nextEvents);
      setTaskDetail(nextTask);
    }).catch(() => {
      setEvents([]);
      setTaskDetail(null);
    });
  }, [selectedTaskId]);

  useEffect(() => {
    if (!selectedJobId) return;
    authedApi(`/api/master/provision/jobs/${selectedJobId}`).then(setJobDetail).catch(() => setJobDetail(null));
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
    await authedApi("/api/master/tasks", { method: "POST", body: JSON.stringify(payload) });
    setNotice("任务已创建");
    await refreshCore();
  };

  const runProvision = async (dryRun) => {
    const result = await authedApi("/api/master/provision/run", {
      method: "POST",
      body: JSON.stringify({ dry_run: dryRun })
    });
    const nextJobId = result?.job?.id;
    if (nextJobId) {
      setSelectedJobId(nextJobId);
      setJobDetail(result);
    }
    setNotice(dryRun ? "演练任务已提交" : "部署任务已提交");
    await refreshCore();
  };

  const syncInfra = async () => {
    const result = await authedApi("/api/master/infra/sync", { method: "POST" });
    setNotice(`基础设施同步完成：${result.count || 0} 条`);
    await refreshCore();
  };

  const syncBiz = async (schedule = false) => {
    const result = await authedApi("/api/master/biz/sync", {
      method: "POST",
      body: JSON.stringify({ schedule })
    });
    setNotice(schedule ? `业务同步并调度完成：${result.count || 0} 条` : `业务同步完成：${result.count || 0} 条`);
    await refreshCore();
  };

  const setProvider = async (provider) => {
    if (provider === "feishu_cli") {
      setNotice("feishu_cli 预留未实现，暂不能作为服务器提供方");
      return;
    }
    await authedApi("/api/master/providers/active", {
      method: "PUT",
      body: JSON.stringify({ provider })
    });
    setNotice(`已切换提供方：${provider}`);
    await refreshCore();
  };

  const validateFeishu = async () => {
    const result = await authedApi("/api/master/providers/feishu-cli/validate", { method: "POST" });
    setFeishuCheck(result);
  };

  const saveToken = () => {
    if (token.trim()) {
      window.localStorage.setItem("master_token", token.trim());
      setNotice("Token 已保存");
      return;
    }
    window.localStorage.removeItem("master_token");
    setNotice("Token 已清空");
  };

  const statusText = (value) => ({
    queued: "排队中",
    dispatched: "已下发",
    running: "执行中",
    success: "成功",
    failed: "失败",
    online: "在线",
    stale: "过期",
    offline: "离线",
    degraded: "降级",
    partial_success: "部分成功"
  }[value] || value || "-");

  return (
    <div className="page">
      <header className="topbar">
        <div>
          <h1>Master Console</h1>
          <p>独立 Master 控制台（不复用 Worker 前端）</p>
        </div>
        <div className="row">
          <input className="token-input" type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="AUTH_TOKEN（可选）" />
          <button onClick={saveToken}>保存 Token</button>
          <button onClick={refreshCore} disabled={loading}>{loading ? "刷新中..." : "刷新"}</button>
        </div>
      </header>

      {error && <div className="error">{error}</div>}
      {notice && <div className="notice">{notice}</div>}

      <section className="cards">
        <div className="card"><span>节点总数</span><strong>{totals.total}</strong></div>
        <div className="card"><span>在线节点</span><strong>{totals.online}</strong></div>
        <div className="card"><span>离线节点</span><strong>{totals.offline}</strong></div>
        <div className="card"><span>过期心跳</span><strong>{totals.stale}</strong></div>
        <div className="card"><span>排队任务</span><strong>{totals.queued}</strong></div>
        <div className="card"><span>下发任务</span><strong>{totals.dispatched}</strong></div>
        <div className="card"><span>执行中任务</span><strong>{totals.running}</strong></div>
        <div className="card"><span>成功/失败</span><strong>{taskStats.success}/{taskStats.failed}</strong></div>
      </section>

      <section className="grid three">
        <div className="panel section-panel">
          <h2>基础设施流</h2>
          <p>只管理 Worker 服务器、部署、心跳、资源、能力和可调度状态。</p>
          <div className="mini-stats">
            <span>Worker：<b>{architectureSummary?.infra?.workers ?? infraWorkers.length}</b></span>
            <span>在线：<b>{architectureSummary?.infra?.online ?? totals.online}</b></span>
            <span>待部署：<b>{architectureSummary?.infra?.pending_deploy ?? 0}</b></span>
            <span>能力：<b>{infraCapabilities.length}</b></span>
          </div>
          <div className="row wrap">
            <button onClick={syncInfra}>同步基础设施 JSON</button>
            <button onClick={() => runProvision(true)}>部署演练</button>
            <button className="warn" onClick={() => runProvision(false)}>真实部署</button>
          </div>
        </div>

        <div className="panel section-panel">
          <h2>业务任务流</h2>
          <p>只处理自动化输入、参数快照、幂等、调度请求、执行结果和回写状态。</p>
          <div className="mini-stats">
            <span>业务任务：<b>{architectureSummary?.biz?.jobs ?? bizJobs.length}</b></span>
            <span>待调度：<b>{architectureSummary?.biz?.pending_schedule ?? 0}</b></span>
            <span>已分配：<b>{architectureSummary?.biz?.assigned ?? 0}</b></span>
            <span>运行记录：<b>{bizRuns.length}</b></span>
          </div>
          <div className="row wrap">
            <button onClick={() => syncBiz(false)}>同步业务 JSON</button>
            <button onClick={() => syncBiz(true)}>同步并调度</button>
          </div>
        </div>

        <div className="panel section-panel">
          <h2>Profile / Worker 监控</h2>
          <p>从 Worker 心跳汇总运行中 Profile、资源和 VNC/CDP 入口信息。</p>
          <div className="mini-stats">
            <span>运行 Profile：<b>{architectureSummary?.infra?.running_profiles ?? totals.running}</b></span>
            <span>Profile 观测：<b>{infraProfiles.length}</b></span>
            <span>Master 队列：<b>{totals.queued}</b></span>
            <span>执行中任务：<b>{totals.running}</b></span>
          </div>
        </div>
      </section>

      <section className="grid two">
        <div className="panel">
          <h2>基础设施：提供方</h2>
          <p>当前：<b>{providers.active || "-"}</b></p>
          <div className="row wrap">
            {providers.providers?.map((name) => {
              const reserved = name === "feishu_cli";
              return (
                <button
                  key={name}
                  onClick={() => setProvider(name)}
                  disabled={reserved}
                  title={reserved ? "feishu_cli 预留未实现" : undefined}
                >
                  {reserved ? `${name}（未实现）` : name}
                </button>
              );
            })}
            <button onClick={validateFeishu}>查看 feishu_cli 状态</button>
          </div>
          {feishuCheck && <p>校验结果：{feishuCheck.ready ? "可用" : "未就绪"}（{feishuCheck.message || "-"}）</p>}
        </div>

        <div className="panel">
          <h2>基础设施：批量部署</h2>
          <p>提供方：<b>{provisionServers.provider || providers.active || "-"}</b></p>
          <p>服务器数：<b>{provisionServers.servers?.length || 0}</b></p>
          <div className="row">
            <button onClick={() => runProvision(true)}>执行演练</button>
            <button className="warn" onClick={() => runProvision(false)}>执行部署</button>
          </div>
        </div>
      </section>

      <section className="grid two">
        <div className="panel">
          <h2>Profile / Worker 监控：节点</h2>
          <table>
            <thead><tr><th>节点</th><th>状态</th><th>负载</th><th>内存</th></tr></thead>
            <tbody>
              {nodes.map((n) => (
                <tr key={n.node_id}>
                  <td>{n.node_id}</td>
                  <td>{statusText(n.status)}</td>
                  <td>{n.running_profiles}/{n.max_profiles}</td>
                  <td>{n.mem_used_mb || 0}/{n.mem_total_mb || 0} MB</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel">
          <h2>业务任务：创建 Master 任务</h2>
          <div className="form">
            <input value={newTask.profile_id} onChange={(e) => setNewTask({ ...newTask, profile_id: e.target.value })} placeholder="profile_id（可选）" />
            <input value={newTask.authorized_target} onChange={(e) => setNewTask({ ...newTask, authorized_target: e.target.value })} placeholder="authorized_target" />
            <select value={newTask.task_type} onChange={(e) => setNewTask({ ...newTask, task_type: e.target.value })}>
              <option value="open_url">open_url</option>
              <option value="external_cdp">external_cdp</option>
            </select>
            <input value={newTask.url} onChange={(e) => setNewTask({ ...newTask, url: e.target.value })} placeholder="url（仅 open_url）" />
            <div className="row">
              <input type="number" value={newTask.timeout_seconds} onChange={(e) => setNewTask({ ...newTask, timeout_seconds: e.target.value })} placeholder="超时秒数" />
              <input type="number" value={newTask.max_retries} onChange={(e) => setNewTask({ ...newTask, max_retries: e.target.value })} placeholder="最大重试" />
            </div>
            <button onClick={createTask}>创建任务</button>
          </div>
        </div>
      </section>

      <section className="grid three">
        <div className="panel">
          <h2>基础设施：部署服务器列表</h2>
          <div className="row between">
            <p>显示：<b>{visibleProvisionServers.length}</b> / {provisionServers.servers?.length || 0}</p>
            <label className="checkbox">
              <input type="checkbox" checked={showEnabledOnly} onChange={(e) => setShowEnabledOnly(e.target.checked)} />
              仅启用
            </label>
          </div>
          <table>
            <thead><tr><th>节点</th><th>主机</th><th>用户</th><th>状态</th></tr></thead>
            <tbody>
              {visibleProvisionServers.map((s) => (
                <tr key={s.node_id}>
                  <td>{s.node_id}</td>
                  <td>{s.host}:{s.port}</td>
                  <td>{s.username}</td>
                  <td>{s.enabled ? "启用" : "禁用"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel">
          <h2>业务任务：Master 任务</h2>
          <select value={selectedTaskId} onChange={(e) => setSelectedTaskId(e.target.value)}>
            <option value="">选择任务</option>
            {tasks.map((t) => (
              <option key={t.id} value={t.id}>{t.id.slice(0, 8)} | {statusText(t.status)} | {t.target_node_id || "未分配"}</option>
            ))}
          </select>
          <div className="detail">
            <p>详情状态：<b>{statusText(taskDetail?.status)}</b></p>
            <p>节点：<b>{taskDetail?.target_node_id || "-"}</b></p>
            <p>类型：<b>{taskDetail?.task_type || "-"}</b></p>
            <p>URL：<b>{taskDetail?.payload?.url || "-"}</b></p>
            <p>失败原因：<b>{taskDetail?.failure_reason || "-"}</b></p>
          </div>
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
          <h2>基础设施：部署任务</h2>
          <select value={selectedJobId} onChange={(e) => setSelectedJobId(e.target.value)}>
            <option value="">选择任务</option>
            {jobs.map((j) => (
              <option key={j.id} value={j.id}>{j.id.slice(0, 8)} | {statusText(j.status)}</option>
            ))}
          </select>
          <div className="detail">
            <p>任务状态：<b>{statusText(jobDetail?.job?.status)}</b></p>
            <p>成功/失败：<b>{jobDetail?.job?.success_count ?? 0}/{jobDetail?.job?.failed_count ?? 0}</b></p>
            <p>总数：<b>{jobDetail?.job?.total_servers ?? 0}</b></p>
            <p>模式：<b>{jobDetail?.job?.dry_run ? "演练" : "真实部署"}</b></p>
          </div>
          <div className="list">
            {jobDetail?.items?.map((it) => (
              <div key={it.id} className="item">
                <b>{it.node_id}</b>
                <span>{statusText(it.status)}</span>
                <p>{it.message || ""}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
