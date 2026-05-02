import { useState, useCallback, useEffect } from "react";
import { Lock, PanelLeftClose, PanelLeft, Plus, Sparkles } from "lucide-react";
import { useProfiles } from "./hooks/useProfiles";
import { api, setOnUnauthorized, type ProfileCreateData } from "./lib/api";
import { ProfileList } from "./components/ProfileList";
import { ProfileForm } from "./components/ProfileForm";
import { LaunchButton } from "./components/LaunchButton";
import { StatusIndicator } from "./components/StatusIndicator";
import { LoginPage } from "./components/LoginPage";
import { OrchestrationPanel } from "./components/OrchestrationPanel";
import { VncWorkspace } from "./components/VncWorkspace";

type AuthState = "checking" | "required" | "ok" | "error";
type View = "empty" | "create" | "edit" | "view";

export default function App() {
  const [authState, setAuthState] = useState<AuthState>("checking");
  const [authRequired, setAuthRequired] = useState(false);

  useEffect(() => {
    setOnUnauthorized(() => setAuthState("required"));

    api.authStatus()
      .then(({ auth_required, authenticated }) => {
        setAuthRequired(auth_required);
        if (!auth_required || authenticated) {
          setAuthState("ok");
        } else {
          setAuthState("required");
        }
      })
      .catch((err) => {
        console.warn("[auth] status check failed:", err);
        setAuthState("error");
      });

    return () => setOnUnauthorized(null);
  }, []);

  if (authState === "checking") {
    return (
      <div className="flex h-screen items-center justify-center bg-[#0a0f1f] text-gray-300">
        <div className="text-sm text-gray-500">Loading...</div>
      </div>
    );
  }

  if (authState === "error") {
    return (
      <div className="flex h-screen items-center justify-center bg-[#0a0f1f] px-6">
        <div className="panel max-w-sm rounded-3xl p-8 text-center">
          <p className="mb-2 text-sm text-red-300">Unable to reach the server</p>
          <button
            onClick={() => {
              setAuthState("checking");
              api.authStatus()
                .then(({ auth_required, authenticated }) => {
                  setAuthRequired(auth_required);
                  setAuthState(!auth_required || authenticated ? "ok" : "required");
                })
                .catch(() => setAuthState("error"));
            }}
            className="text-xs text-gray-400 underline hover:text-gray-200"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (authState === "required") {
    return <LoginPage onSuccess={() => setAuthState("ok")} />;
  }

  return (
    <AppContent
      authRequired={authRequired}
      onLogout={async () => {
        await api.logout();
        setAuthState("required");
      }}
    />
  );
}

interface AppContentProps {
  authRequired: boolean;
  onLogout: () => void;
}

function AppContent({ authRequired, onLogout }: AppContentProps) {
  const { profiles, loading, error, create, update, remove, launch, stop } = useProfiles();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<View>("empty");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [viewerIds, setViewerIds] = useState<string[]>([]);
  const [activeViewerId, setActiveViewerId] = useState<string | null>(null);

  const selected = profiles.find((p) => p.id === selectedId) ?? null;
  const runningCount = profiles.filter((profile) => profile.status === "running").length;

  const openViewer = useCallback((profileId: string) => {
    setViewerIds((current) => current.includes(profileId) ? current : [...current, profileId]);
    setActiveViewerId(profileId);
    setView("view");
  }, []);

  useEffect(() => {
    const runningIds = new Set(profiles.filter((profile) => profile.status === "running").map((profile) => profile.id));

    setViewerIds((current) => current.filter((id) => runningIds.has(id)));
    setActiveViewerId((current) => {
      if (current && runningIds.has(current)) return current;
      const nextViewer = viewerIds.filter((id) => runningIds.has(id));
      return nextViewer.length > 0 ? (nextViewer[nextViewer.length - 1] ?? null) : null;
    });
  }, [profiles, viewerIds]);

  const handleSelect = useCallback((id: string) => {
    setSelectedId(id);
    const profile = profiles.find((p) => p.id === id);
    if (profile?.status === "running") {
      openViewer(id);
      return;
    }
    setView("edit");
  }, [openViewer, profiles]);

  const handleNew = useCallback(() => {
    setSelectedId(null);
    setView("create");
  }, []);

  const handleCreate = useCallback(async (data: ProfileCreateData) => {
    const profile = await create(data);
    if (profile) {
      setSelectedId(profile.id);
      setView("edit");
    }
  }, [create]);

  const handleUpdate = useCallback(async (data: ProfileCreateData) => {
    if (!selectedId) return;
    await update(selectedId, data);
  }, [selectedId, update]);

  const handleDelete = useCallback(async () => {
    if (!selectedId) return;
    await remove(selectedId);
    setViewerIds((current) => current.filter((id) => id !== selectedId));
    setActiveViewerId((current) => current === selectedId ? null : current);
    setSelectedId(null);
    setView("empty");
  }, [selectedId, remove]);

  const handleLaunch = useCallback(async () => {
    if (!selectedId) return;
    const result = await launch(selectedId);
    if (result) openViewer(selectedId);
  }, [selectedId, launch, openViewer]);

  const handleStop = useCallback(async () => {
    if (!selectedId) return;
    await stop(selectedId);
    setViewerIds((current) => current.filter((id) => id !== selectedId));
    setActiveViewerId((current) => current === selectedId ? null : current);
    setView("edit");
  }, [selectedId, stop]);

  const handleCloseViewer = useCallback((profileId: string) => {
    setViewerIds((current) => {
      const next = current.filter((id) => id !== profileId);
      setActiveViewerId((active) => {
        if (active !== profileId) return active;
        return next.length > 0 ? (next[next.length - 1] ?? null) : null;
      });
      if (view === "view" && next.length === 0) {
        setView("empty");
      }
      return next;
    });
  }, [view]);

  const handleActivateViewer = useCallback((profileId: string) => {
    setSelectedId(profileId);
    setActiveViewerId(profileId);
    setView("view");
  }, []);

  const handleVncDisconnect = useCallback((profileId: string) => {
    setViewerIds((current) => {
      const next = current.filter((id) => id !== profileId);
      setActiveViewerId((active) => active === profileId ? (next.length > 0 ? (next[next.length - 1] ?? null) : null) : active);
      if (next.length === 0) {
        setView("empty");
      }
      return next;
    });
  }, []);

  const showEmptyState = view === "empty" && viewerIds.length === 0;
  const showOrchestration = view !== "create" && view !== "edit";

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#0a0f1f] text-gray-300">
        <div className="text-sm text-gray-500">Loading...</div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-[radial-gradient(circle_at_top,_rgba(59,130,246,0.14),_transparent_32%),linear-gradient(180deg,#0a0f1f_0%,#0f172a_100%)] text-gray-100">
      {sidebarOpen && (
        <div className="w-80 shrink-0 border-r border-white/10 bg-slate-950/55 backdrop-blur">
          <ProfileList
            profiles={profiles}
            selectedId={selectedId}
            onSelect={handleSelect}
            onNew={handleNew}
          />
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="border-b border-white/10 bg-slate-950/35 px-5 py-4 backdrop-blur">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-start gap-3">
              <button
                onClick={() => setSidebarOpen(!sidebarOpen)}
                className="mt-0.5 rounded-lg border border-white/10 bg-white/5 p-2 text-gray-400 transition hover:bg-white/10 hover:text-gray-100"
                title={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
              >
                {sidebarOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeft className="h-4 w-4" />}
              </button>
              <div>
                <div className="flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-sky-300/80">
                  <Sparkles className="h-3.5 w-3.5" />
                  Profile Workspace
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-3">
                  <h1 className="text-xl font-semibold tracking-tight text-white">CloakBrowser Manager</h1>
                  <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2.5 py-1 text-xs font-medium text-emerald-300">
                    {runningCount} running
                  </span>
                  <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-xs font-medium text-gray-300">
                    {profiles.length} profiles
                  </span>
                </div>
                <p className="mt-1 text-sm text-gray-400">
                  在一个视图里管理配置、启动状态和本地编排任务。
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 lg:justify-end">
              {selected && (
                <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-2">
                  <div className="flex items-center gap-2">
                    <StatusIndicator status={selected.status} size="md" />
                    <span className="text-sm font-medium text-white">{selected.name}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-xs text-gray-400">
                    <span className="capitalize">{selected.platform}</span>
                    {selected.proxy && <span>Proxy enabled</span>}
                    {selected.headless && <span>Headless</span>}
                  </div>
                </div>
              )}

              {!selected && (
                <button onClick={handleNew} className="btn-secondary flex items-center gap-1.5">
                  <Plus className="h-3.5 w-3.5" />
                  <span>New Profile</span>
                </button>
              )}

              {selected && (
                <LaunchButton
                  status={selected.status}
                  onLaunch={handleLaunch}
                  onStop={handleStop}
                />
              )}

              {authRequired && (
                <button
                  onClick={onLogout}
                  className="rounded-lg border border-white/10 bg-white/5 p-2 text-gray-400 transition hover:bg-white/10 hover:text-white"
                  title="Log out"
                >
                  <Lock className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>
        </div>

        {error && (
          <div className="mx-5 mt-4 rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200 shadow-[0_12px_30px_rgba(127,29,29,0.18)]">
            {error}
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-5 py-5">
          <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
            <VncWorkspace
              profiles={profiles}
              viewerIds={viewerIds}
              activeViewerId={activeViewerId}
              onActivate={handleActivateViewer}
              onClose={handleCloseViewer}
              onDisconnect={handleVncDisconnect}
            />

            {showEmptyState && (
              <div className="panel flex min-h-[320px] items-center justify-center rounded-[28px] p-8">
                <div className="max-w-md text-center">
                  <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-sky-400/20 bg-sky-400/10 text-sky-300">
                    <Sparkles className="h-6 w-6" />
                  </div>
                  <h2 className="text-xl font-semibold text-white">先选一个 Profile，或者新建一个</h2>
                  <p className="mt-2 text-sm leading-6 text-gray-400">
                    左侧列表负责快速切换，右侧区域负责编辑配置、启动浏览器以及查看 VNC 会话。
                  </p>
                  <button onClick={handleNew} className="btn-primary mt-5 inline-flex items-center gap-1.5">
                    <Plus className="h-4 w-4" />
                    <span>Create Profile</span>
                  </button>
                </div>
              </div>
            )}

            {view === "create" && (
              <div className="panel rounded-[28px] p-2 sm:p-4">
                <ProfileForm
                  profile={null}
                  onSave={handleCreate}
                  onCancel={() => setView("empty")}
                />
              </div>
            )}

            {view === "edit" && selected && (
              <div className="panel rounded-[28px] p-2 sm:p-4">
                <ProfileForm
                  profile={selected}
                  onSave={handleUpdate}
                  onDelete={handleDelete}
                  onCancel={() => {
                    setSelectedId(null);
                    setView("empty");
                  }}
                />
              </div>
            )}

            {showOrchestration && <OrchestrationPanel profiles={profiles} />}
          </div>
        </div>
      </div>
    </div>
  );
}
