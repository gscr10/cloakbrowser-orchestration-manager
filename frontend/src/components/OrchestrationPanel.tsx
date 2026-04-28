import { Activity, Play, Plus, Upload } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type Profile, type ProxyEndpoint, type Run, type SchedulerStatus, type Task } from "../lib/api";

interface OrchestrationPanelProps {
  profiles: Profile[];
}

const EMPTY_PROXY_CSV = "protocol,host,port,username,password,region,tags\nhttp,127.0.0.1,8080,,,,local";

export function OrchestrationPanel({ profiles }: OrchestrationPanelProps) {
  const [proxies, setProxies] = useState<ProxyEndpoint[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [status, setStatus] = useState<SchedulerStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [csvText, setCsvText] = useState(EMPTY_PROXY_CSV);
  const [profileId, setProfileId] = useState("");
  const [authorizedTarget, setAuthorizedTarget] = useState("internal test app");
  const [taskType, setTaskType] = useState<"open_url" | "external_cdp">("open_url");
  const [url, setUrl] = useState("https://example.com");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [nextProxies, nextTasks, nextRuns, nextStatus] = await Promise.all([
        api.listProxies(),
        api.listTasks(),
        api.listRuns(),
        api.getSchedulerStatus(),
      ]);
      setProxies(nextProxies);
      setTasks(nextTasks);
      setRuns(nextRuns);
      setStatus(nextStatus);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load orchestration state");
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = window.setInterval(refresh, 3000);
    return () => window.clearInterval(interval);
  }, [refresh]);

  useEffect(() => {
    const firstProfile = profiles[0];
    if (!profileId && firstProfile) setProfileId(firstProfile.id);
  }, [profileId, profiles]);

  const importCsv = async () => {
    setBusy(true);
    try {
      const result = await api.importProxies(csvText);
      setError(result.errors.length ? `${result.created.length} imported, ${result.errors.length} failed` : null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to import proxies");
    } finally {
      setBusy(false);
    }
  };

  const createTask = async () => {
    if (!profileId || !authorizedTarget.trim()) return;
    setBusy(true);
    try {
      await api.createTask({
        profile_id: profileId,
        authorized_target: authorizedTarget,
        task_type: taskType,
        url: taskType === "open_url" ? url : null,
        timeout_seconds: 300,
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create task");
    } finally {
      setBusy(false);
    }
  };

  const tick = async () => {
    setBusy(true);
    try {
      await api.tickScheduler();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scheduler tick failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border-t border-border bg-surface-0 p-4">
      <div className="grid gap-4 lg:grid-cols-[1fr_1fr_1.2fr]">
        <section className="rounded-lg border border-border bg-surface-1 p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Proxy Pool</h2>
            <span className="text-xs text-gray-500">{proxies.length} endpoints</span>
          </div>
          <textarea
            className="input min-h-28 font-mono text-xs"
            value={csvText}
            onChange={(event) => setCsvText(event.target.value)}
          />
          <button disabled={busy} onClick={importCsv} className="btn-secondary mt-3 flex items-center gap-1.5">
            <Upload className="h-3.5 w-3.5" />
            Import CSV
          </button>
          <div className="mt-3 max-h-28 overflow-y-auto text-xs text-gray-400">
            {proxies.slice(0, 5).map((proxy) => (
              <div key={proxy.id} className="flex justify-between border-t border-border py-1.5">
                <span>{proxy.name}</span>
                <span>{proxy.health}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-lg border border-border bg-surface-1 p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Task Queue</h2>
            <span className="text-xs text-gray-500">{status?.queued_count ?? 0} queued</span>
          </div>
          <label className="label">Profile</label>
          <select className="input mb-3" value={profileId} onChange={(event) => setProfileId(event.target.value)}>
            {profiles.map((profile) => (
              <option key={profile.id} value={profile.id}>{profile.name}</option>
            ))}
          </select>
          <label className="label">Authorized target</label>
          <input className="input mb-3" value={authorizedTarget} onChange={(event) => setAuthorizedTarget(event.target.value)} />
          <label className="label">Task type</label>
          <select className="input mb-3" value={taskType} onChange={(event) => setTaskType(event.target.value as "open_url" | "external_cdp")}>
            <option value="open_url">Open URL</option>
            <option value="external_cdp">External CDP</option>
          </select>
          {taskType === "open_url" && (
            <>
              <label className="label">URL</label>
              <input className="input mb-3" value={url} onChange={(event) => setUrl(event.target.value)} />
            </>
          )}
          <div className="flex gap-2">
            <button disabled={busy || !profiles.length} onClick={createTask} className="btn-primary flex items-center gap-1.5">
              <Plus className="h-3.5 w-3.5" />
              Enqueue
            </button>
            <button disabled={busy} onClick={tick} className="btn-secondary flex items-center gap-1.5">
              <Play className="h-3.5 w-3.5" />
              Run Tick
            </button>
          </div>
        </section>

        <section className="rounded-lg border border-border bg-surface-1 p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Scheduler</h2>
            <span className="flex items-center gap-1 text-xs text-gray-500">
              <Activity className="h-3.5 w-3.5" />
              {status ? `${status.running_count}/${status.max_running} running` : "loading"}
            </span>
          </div>
          {error && <div className="mb-3 rounded border border-red-600/30 bg-red-600/15 p-2 text-xs text-red-400">{error}</div>}
          <div className="max-h-56 overflow-y-auto text-xs">
            {tasks.length === 0 && <div className="text-gray-500">No tasks yet</div>}
            {tasks.slice(0, 8).map((task) => (
              <div key={task.id} className="border-t border-border py-2">
                <div className="flex justify-between gap-3">
                  <span className="font-medium text-gray-200">{task.task_type}</span>
                  <span className="text-gray-500">{task.status}</span>
                </div>
                <div className="mt-1 truncate text-gray-500">{task.url || task.authorized_target}</div>
                {task.failure_reason && <div className="mt-1 text-red-400">{task.failure_reason}</div>}
              </div>
            ))}
          </div>
          <div className="mt-3 border-t border-border pt-3 text-xs text-gray-500">
            {runs.length} recorded runs
          </div>
        </section>
      </div>
    </div>
  );
}
