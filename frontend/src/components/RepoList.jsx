import { useEffect, useMemo, useRef, useState } from "react";
import { listRepos, syncRepos } from "../api/client";
import { timeSince, daysSince } from "../utils/time";

// Repos with no push in this many days are flagged as stale
const STALE_DAYS = 90;

function Badge({ children, tone }) {
  return <span className={`badge ${tone || ""}`}>{children}</span>;
}

export default function RepoList({ onOpen, openingUrl }) {
  const [repos, setRepos] = useState([]);
  const [syncedAt, setSyncedAt] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("");
  const [hideArchived, setHideArchived] = useState(true);
  const [hideForks, setHideForks] = useState(false);

  const apply = (data) => {
    setRepos(data.repos);
    setSyncedAt(data.synced_at);
  };

  const sync = async () => {
    setSyncing(true);
    setError(null);
    try {
      apply(await syncRepos());
    } catch (e) {
      setError(e.message);
    } finally {
      setSyncing(false);
    }
  };

  // Show stored repos immediately; sync from GitHub on first visit when nothing is stored yet.
  // The ref keeps React StrictMode's double effect run from firing two syncs.
  const initialized = useRef(false);
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    listRepos()
      .then(data => {
        apply(data);
        if (!data.synced_at) sync();
      })
      .catch(e => setError(e.message));
  }, []);

  const visible = useMemo(() => {
    const q = filter.toLowerCase();
    return repos.filter(r =>
      (!hideArchived || !r.archived) &&
      (!hideForks || !r.fork) &&
      (!q || r.full_name.toLowerCase().includes(q) || (r.description || "").toLowerCase().includes(q))
    );
  }, [repos, filter, hideArchived, hideForks]);

  const staleCount = visible.filter(r => !r.archived && daysSince(r.pushed_at) > STALE_DAYS).length;

  return (
    <div className="repo-list">
      <div className="repo-list-toolbar">
        <input
          className="repo-filter"
          type="text"
          placeholder="Filter repos…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
        />
        <label className="toggle">
          <input type="checkbox" checked={hideArchived} onChange={e => setHideArchived(e.target.checked)} />
          Hide archived
        </label>
        <label className="toggle">
          <input type="checkbox" checked={hideForks} onChange={e => setHideForks(e.target.checked)} />
          Hide forks
        </label>
        <span className="repo-list-summary">
          {visible.length} repos{staleCount > 0 && ` · ${staleCount} stale`}
          {syncedAt && ` · synced ${timeSince(syncedAt)}`}
        </span>
        <button className="load-btn" onClick={sync} disabled={syncing}>
          {syncing ? "Syncing…" : "Sync from GitHub"}
        </button>
      </div>

      {error && <div className="repo-list-error">⚠ {error}</div>}

      <div className="repo-table-wrap">
        <table className="repo-table">
          <thead>
            <tr>
              <th>Repository</th>
              <th>Language</th>
              <th>Last push</th>
              <th className="num">Issues</th>
              <th className="num">Stars</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {visible.map(r => {
              const stale = !r.archived && daysSince(r.pushed_at) > STALE_DAYS;
              return (
                <tr key={r.id} className={r.archived ? "archived" : ""}>
                  <td>
                    <div className="repo-name">
                      <a href={r.html_url} target="_blank" rel="noreferrer">{r.full_name}</a>
                      {r.private && <Badge>private</Badge>}
                      {r.fork && <Badge>fork</Badge>}
                      {r.archived && <Badge>archived</Badge>}
                      {stale && <Badge tone="warn">stale</Badge>}
                    </div>
                    {r.description && <div className="repo-desc">{r.description}</div>}
                  </td>
                  <td className="mono">{r.language || "—"}</td>
                  <td className="mono">{timeSince(r.pushed_at)}</td>
                  <td className="num mono">{r.open_issues}</td>
                  <td className="num mono">{r.stars}</td>
                  <td className="num">
                    <button
                      className="open-btn"
                      onClick={() => onOpen(r.html_url)}
                      disabled={!!openingUrl}
                    >
                      {openingUrl === r.html_url ? "Loading…" : "Open"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {visible.length === 0 && !syncing && (
          <div className="repo-list-empty">
            {repos.length === 0 ? "No repos stored yet — click “Sync from GitHub”." : "No repos match the filters."}
          </div>
        )}
      </div>
    </div>
  );
}
