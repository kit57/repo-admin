import { useEffect, useMemo, useRef, useState } from "react";
import { listRepos, syncRepos } from "../api/client";
import { timeSince, daysSince } from "../utils/time";

// Repos with no push in this many days are flagged as stale
const STALE_DAYS = 90;
const DEFAULT_SORT = { column: "pushed_at", direction: "desc" };
const SORT_DIRECTIONS = {
  full_name: "asc",
  language: "asc",
  pushed_at: "desc",
  open_issues: "desc",
  stars: "desc",
};

function compareRepos(a, b, column, direction) {
  const aValue = a[column];
  const bValue = b[column];
  const aEmpty = aValue == null || aValue === "";
  const bEmpty = bValue == null || bValue === "";

  if (aEmpty || bEmpty) return aEmpty === bEmpty ? 0 : aEmpty ? 1 : -1;
  if (column === "full_name" || column === "language") {
    return direction * String(aValue).localeCompare(String(bValue), undefined, { sensitivity: "base" });
  }
  if (column === "pushed_at") return direction * (new Date(aValue).getTime() - new Date(bValue).getTime());
  return direction * (aValue - bValue);
}

function Badge({ children, tone }) {
  return <span className={`badge ${tone || ""}`}>{children}</span>;
}

export default function RepoList({ onOpen, openingUrl, openError, onRetryOpen }) {
  const [repos, setRepos] = useState([]);
  const [syncedAt, setSyncedAt] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("");
  const [hideArchived, setHideArchived] = useState(true);
  const [hideForks, setHideForks] = useState(false);
  const [sort, setSort] = useState(DEFAULT_SORT);

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
    const filtered = repos.filter(r =>
      (!hideArchived || !r.archived) &&
      (!hideForks || !r.fork) &&
      (!q || r.full_name.toLowerCase().includes(q) || (r.description || "").toLowerCase().includes(q))
    );
    const direction = sort.direction === "asc" ? 1 : -1;
    return filtered.sort((a, b) => compareRepos(a, b, sort.column, direction));
  }, [repos, filter, hideArchived, hideForks, sort]);

  const toggleSort = column => {
    setSort(current => current.column === column
      ? { column, direction: current.direction === "asc" ? "desc" : "asc" }
      : { column, direction: SORT_DIRECTIONS[column] }
    );
  };

  const sortHeader = (label, column, numeric = false) => {
    const active = sort.column === column;
    const direction = active ? sort.direction : null;
    const arrow = direction === "asc" ? "↑" : "↓";
    return (
      <th className={numeric ? "num" : undefined} aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}>
        <button className="repo-sort-button" onClick={() => toggleSort(column)}>
          {label}{active && <span aria-hidden="true"> {arrow}</span>}
        </button>
      </th>
    );
  };

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
      {openError && (
        <div className="repo-list-error" role="alert">
          Could not open repository: {openError}
          {onRetryOpen && (
            <button className="open-btn" onClick={onRetryOpen} disabled={!!openingUrl}>
              Retry
            </button>
          )}
        </div>
      )}

      <div className="repo-table-wrap">
        <table className="repo-table">
          <thead>
            <tr>
              {sortHeader("Repository", "full_name")}
              {sortHeader("Language", "language")}
              {sortHeader("Last push", "pushed_at")}
              {sortHeader("Issues", "open_issues", true)}
              {sortHeader("Stars", "stars", true)}
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
                      aria-label={`${openingUrl === r.html_url ? "Opening" : "Open"} ${r.full_name}`}
                    >
                      {openingUrl === r.html_url ? "Opening…" : "Open"}
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
