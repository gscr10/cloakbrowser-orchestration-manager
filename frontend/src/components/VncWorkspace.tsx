import { Monitor, X } from "lucide-react";
import type { Profile } from "../lib/api";
import { StatusIndicator } from "./StatusIndicator";
import { ProfileViewer } from "./ProfileViewer";

interface VncWorkspaceProps {
  profiles: Profile[];
  viewerIds: string[];
  activeViewerId: string | null;
  onActivate: (id: string) => void;
  onClose: (id: string) => void;
  onDisconnect: (id: string) => void;
}

export function VncWorkspace({
  profiles,
  viewerIds,
  activeViewerId,
  onActivate,
  onClose,
  onDisconnect,
}: VncWorkspaceProps) {
  const openProfiles = viewerIds
    .map((id) => profiles.find((profile) => profile.id === id) ?? null)
    .filter((profile): profile is Profile => profile !== null && profile.status === "running");

  if (openProfiles.length === 0) {
    return null;
  }

  return (
    <section className="panel rounded-[28px] p-4 sm:p-5">
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-sky-300/80">
            <Monitor className="h-3.5 w-3.5" />
            VNC Workspace
          </div>
          <h2 className="mt-1 text-lg font-semibold text-white">保持已连接会话，并排查看多个 Profile</h2>
          <p className="mt-1 text-sm text-gray-400">
            切换运行中的 Profile 时会保留现有连接；关闭卡片前不会主动断开对应会话。
          </p>
        </div>
        <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-gray-300">
          {openProfiles.length} active viewer{openProfiles.length > 1 ? "s" : ""}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        {openProfiles.map((profile) => {
          const active = activeViewerId === profile.id;
          return (
            <article
              key={profile.id}
              className={`flex min-h-0 flex-col overflow-hidden rounded-[24px] border bg-slate-950/70 shadow-[0_18px_60px_rgba(15,23,42,0.45)] transition ${
                active
                  ? "border-sky-400/40 ring-1 ring-sky-400/25"
                  : "border-white/10"
               }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 bg-white/[0.03] px-4 py-3">
                <button
                  onClick={() => onActivate(profile.id)}
                  className="min-w-0 text-left"
                  title="Focus this viewer"
                >
                  <div className="flex items-center gap-2">
                    <StatusIndicator status={profile.status} size="md" />
                    <span className="truncate text-sm font-semibold text-white">{profile.name}</span>
                    {active && (
                      <span className="rounded-full border border-sky-400/20 bg-sky-400/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-sky-300">
                        Focused
                      </span>
                    )}
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-xs text-gray-400">
                    <span className="capitalize">{profile.platform}</span>
                    {profile.proxy && <span>Proxy enabled</span>}
                    {profile.headless && <span>Headless</span>}
                  </div>
                </button>

                <div className="flex items-center gap-2">
                  {!active && (
                    <button
                      onClick={() => onActivate(profile.id)}
                      className="btn-secondary px-3 py-1.5 text-xs"
                    >
                      Focus
                    </button>
                  )}
                  <button
                    onClick={() => onClose(profile.id)}
                    className="rounded-lg border border-white/10 bg-white/5 p-2 text-gray-400 transition hover:bg-white/10 hover:text-white"
                    title="Close viewer"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              <div className="h-[420px] min-h-[420px] bg-black xl:h-[520px]">
                <ProfileViewer
                  profileId={profile.id}
                  cdpUrl={profile.cdp_url}
                  clipboardSync={profile.clipboard_sync}
                  onDisconnect={onDisconnect}
                />
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
