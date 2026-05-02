import { Plus, Search, Monitor } from "lucide-react";
import { useState } from "react";
import type { Profile } from "../lib/api";
import { StatusIndicator } from "./StatusIndicator";

interface ProfileListProps {
  profiles: Profile[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}

export function ProfileList({ profiles, selectedId, onSelect, onNew }: ProfileListProps) {
  const [search, setSearch] = useState("");

  const filtered = profiles
    .filter((p) => p.name.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {
      if (a.status !== b.status) return a.status === "running" ? -1 : 1;
      return a.name.localeCompare(b.name);
    });

  const runningCount = profiles.filter((p) => p.status === "running").length;

  return (
    <div className="flex flex-col h-full">
      <div className="border-b border-white/10 px-4 py-5">
        <div className="mb-4 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-sky-400/20 bg-sky-400/10 text-sky-300">
            <Monitor className="h-4 w-4" />
          </div>
          <div>
            <h1 className="text-sm font-semibold tracking-tight text-white">Profiles</h1>
            <p className="text-xs text-gray-500">快速切换、查看状态并进入编辑</p>
          </div>
        </div>

        <div className="mb-4 grid grid-cols-2 gap-2">
          <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2">
            <div className="text-[11px] uppercase tracking-wide text-gray-500">Running</div>
            <div className="mt-1 text-lg font-semibold text-white">{runningCount}</div>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2">
            <div className="text-[11px] uppercase tracking-wide text-gray-500">Total</div>
            <div className="mt-1 text-lg font-semibold text-white">{profiles.length}</div>
          </div>
        </div>

        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
          <input
            type="text"
            placeholder="Search profiles..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="input pl-9 text-sm"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {filtered.length === 0 && (
          <div className="rounded-2xl border border-dashed border-white/10 px-4 py-8 text-center text-xs text-gray-500">
            {profiles.length === 0 ? "No profiles yet" : "No matches"}
          </div>
        )}
        {filtered.map((profile) => (
          <button
            key={profile.id}
            onClick={() => onSelect(profile.id)}
            className={`mb-2 w-full rounded-2xl border px-3.5 py-3 text-left transition ${
              selectedId === profile.id
                ? "border-sky-400/30 bg-sky-400/10 shadow-[0_12px_30px_rgba(14,165,233,0.12)]"
                : "border-transparent bg-white/[0.03] hover:border-white/10 hover:bg-white/[0.06]"
            }`}
          >
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <StatusIndicator status={profile.status} />
                <span className="truncate text-sm font-medium text-white">{profile.name}</span>
              </div>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${
                profile.status === "running"
                  ? "bg-emerald-400/10 text-emerald-300"
                  : "bg-white/5 text-gray-400"
              }`}>
                {profile.status}
              </span>
            </div>

            <div className="mt-2 flex items-center gap-2 text-xs text-gray-500">
              <span className="capitalize">{profile.platform}</span>
              {profile.proxy && <span>Proxy</span>}
              {profile.headless && <span>Headless</span>}
            </div>

            {profile.tags.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {profile.tags.slice(0, 4).map((t) => (
                  <span
                    key={t.tag}
                    className="rounded-full px-2 py-0.5 text-[10px]"
                    style={t.color ? { backgroundColor: `${t.color}20`, color: t.color } : undefined}
                  >
                    {t.tag}
                  </span>
                ))}
                {profile.tags.length > 4 && (
                  <span className="rounded-full bg-white/5 px-2 py-0.5 text-[10px] text-gray-400">
                    +{profile.tags.length - 4}
                  </span>
                )}
              </div>
            )}
          </button>
        ))}
      </div>

      <div className="border-t border-white/10 p-4">
        <button onClick={onNew} className="btn-primary flex w-full items-center justify-center gap-1.5">
          <Plus className="h-3.5 w-3.5" />
          <span>New Profile</span>
        </button>
      </div>
    </div>
  );
}
