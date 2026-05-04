/**
 * API client for CloakBrowser Manager backend.
 */

export interface Profile {
  id: string;
  name: string;
  fingerprint_seed: number;
  proxy: string | null;
  timezone: string | null;
  locale: string | null;
  platform: string;
  user_agent: string | null;
  screen_width: number;
  screen_height: number;
  gpu_vendor: string | null;
  gpu_renderer: string | null;
  hardware_concurrency: number | null;
  humanize: boolean;
  human_preset: string;
  headless: boolean;
  geoip: boolean;
  clipboard_sync: boolean;
  color_scheme: string | null;
  launch_args: string[];
  notes: string | null;
  user_data_dir: string;
  created_at: string;
  updated_at: string;
  tags: { tag: string; color: string | null }[];
  status: "running" | "stopped";
  vnc_ws_port: number | null;
  cdp_url: string | null;
}

export interface ProfileCreateData {
  name: string;
  fingerprint_seed?: number | null;
  proxy?: string | null;
  timezone?: string | null;
  locale?: string | null;
  platform?: string;
  user_agent?: string | null;
  screen_width?: number;
  screen_height?: number;
  gpu_vendor?: string | null;
  gpu_renderer?: string | null;
  hardware_concurrency?: number | null;
  humanize?: boolean;
  human_preset?: string;
  headless?: boolean;
  geoip?: boolean;
  clipboard_sync?: boolean;
  color_scheme?: string | null;
  launch_args?: string[];
  notes?: string | null;
  tags?: { tag: string; color: string | null }[];
}

export interface LaunchResult {
  profile_id: string;
  status: string;
  vnc_ws_port: number;
  display: string;
  cdp_url: string | null;
}

export interface SystemStatus {
  running_count: number;
  binary_version: string;
  profiles_total: number;
}

export interface ProxyEndpoint {
  id: string;
  name: string;
  protocol: "http" | "https" | "socks5";
  host: string;
  port: number;
  username: string | null;
  region: string | null;
  tags: string[];
  health: string;
  created_at: string;
  updated_at: string;
}

export interface Task {
  id: string;
  profile_id: string;
  authorized_target: string;
  task_type: "open_url" | "external_cdp";
  url: string | null;
  status: string;
  proxy_id: string | null;
  run_id: string | null;
  failure_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface Run {
  id: string;
  profile_id: string;
  task_id: string | null;
  proxy_id: string | null;
  status: string;
  started_at: string;
  stopped_at: string | null;
  failure_reason: string | null;
}

export interface SchedulerStatus {
  queued_count: number;
  running_count: number;
  max_running: number;
}


class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

// Global 401 callback — set by App to trigger login page on auth failure
let _onUnauthorized: (() => void) | null = null;
export function setOnUnauthorized(cb: (() => void) | null) {
  _onUnauthorized = cb;
}

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    if (res.status === 401 && _onUnauthorized) {
      _onUnauthorized();
      throw new ApiError(401, "Unauthorized");
    }
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || res.statusText);
  }
  return res.json();
}

export const api = {
  authStatus: () =>
    request<{ auth_required: boolean; authenticated: boolean }>("/api/auth/status"),

  login: (token: string) =>
    request<{ ok: boolean }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),

  logout: () =>
    request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),

  listProfiles: () => request<Profile[]>("/api/profiles"),

  getProfile: (id: string) => request<Profile>(`/api/profiles/${id}`),

  createProfile: (data: ProfileCreateData) =>
    request<Profile>("/api/profiles", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  updateProfile: (id: string, data: Partial<ProfileCreateData>) =>
    request<Profile>(`/api/profiles/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  deleteProfile: (id: string) =>
    request<{ ok: boolean }>(`/api/profiles/${id}`, { method: "DELETE" }),

  launchProfile: (id: string) =>
    request<LaunchResult>(`/api/profiles/${id}/launch`, { method: "POST" }),

  stopProfile: (id: string) =>
    request<{ ok: boolean }>(`/api/profiles/${id}/stop`, { method: "POST" }),

  getStatus: () => request<SystemStatus>("/api/status"),

  listProxies: () => request<ProxyEndpoint[]>("/api/proxies"),

  createProxy: (data: {
    name?: string | null;
    protocol: "http" | "https" | "socks5";
    host: string;
    port: number;
    username?: string | null;
    password?: string | null;
    region?: string | null;
    tags?: string[];
  }) =>
    request<ProxyEndpoint>("/api/proxies", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  importProxies: (csv: string) =>
    request<{ created: ProxyEndpoint[]; errors: { line: number; error: string }[] }>("/api/proxies/import", {
      method: "POST",
      body: JSON.stringify({ csv }),
    }),

  listTasks: () => request<Task[]>("/api/tasks"),

  createTask: (data: {
    profile_id: string;
    authorized_target: string;
    task_type: "open_url" | "external_cdp";
    url?: string | null;
    timeout_seconds?: number;
  }) =>
    request<Task>("/api/tasks", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  cancelTask: (id: string) => request<Task>(`/api/tasks/${id}/cancel`, { method: "POST" }),

  listRuns: () => request<Run[]>("/api/runs"),

  getSchedulerStatus: () => request<SchedulerStatus>("/api/scheduler/status"),

  tickScheduler: () => request<SchedulerStatus>("/api/scheduler/tick", { method: "POST" }),

  setClipboard: (id: string, text: string) =>
    request<{ ok: boolean }>(`/api/profiles/${id}/clipboard`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  getClipboard: (id: string) =>
    request<{ text: string }>(`/api/profiles/${id}/clipboard`),
};
