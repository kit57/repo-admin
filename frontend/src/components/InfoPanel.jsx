import { useMemo } from "react";

function StatRow({ label, value, color }) {
  return (
    <div className="stat-row">
      <span className="stat-label">{label}</span>
      <span className={`stat-val ${color || ""}`}>{value}</span>
    </div>
  );
}

function LangBar({ name, bytes, total }) {
  const pct = total > 0 ? Math.round((bytes / total) * 100) : 0;
  const colors = {
    Python: "var(--accent)", TypeScript: "var(--accent2)", JavaScript: "#f7df1e",
    Go: "#00acd7", Rust: "#f74c00", Ruby: "#cc342d", default: "var(--text3)",
  };
  const color = colors[name] || colors.default;
  return (
    <div className="lang-bar">
      <div className="lang-bar-label">
        <span>{name}</span>
        <span>{pct}%</span>
      </div>
      <div className="lang-bar-track">
        <div className="lang-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

function timeSince(dateStr) {
  if (!dateStr) return "—";
  const diff = Date.now() - new Date(dateStr).getTime();
  const h = Math.floor(diff / 3600000);
  if (h < 1) return "< 1h ago";
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function InfoPanel({ repo, messages, contextFiles }) {
  const meta = repo?.meta;

  const totalLangBytes = useMemo(() => {
    if (!meta?.languages) return 0;
    return Object.values(meta.languages).reduce((a, b) => a + b, 0);
  }, [meta]);

  const topLangs = useMemo(() => {
    if (!meta?.languages) return [];
    return Object.entries(meta.languages)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 4);
  }, [meta]);

  const aiMessages = messages.filter(m => m.role === "assistant").length;
  const tokenEstimate = messages.reduce((acc, m) => acc + Math.round(m.content.length / 4), 0);

  return (
    <div className="right-panel">
      <div className="panel-tabs">
        <div className="ptab active">Info</div>
      </div>
      <div className="panel-body">
        {!repo ? (
          <div style={{ color: "var(--text3)", fontSize: 12, marginTop: 16, textAlign: "center" }}>
            No repo loaded
          </div>
        ) : (
          <>
            <StatRow label="Repository" value={meta?.full_name?.split("/")[1]} color="blue" />
            <StatRow label="Files indexed" value={repo.file_count?.toLocaleString()} color="green" />
            <StatRow label="Stars" value={meta?.stars?.toLocaleString()} />
            <StatRow label="Forks" value={meta?.forks?.toLocaleString()} />
            <StatRow label="Open issues" value={meta?.open_issues} />
            <StatRow label="Last push" value={timeSince(meta?.last_push)} />
            <StatRow label="Model" value="sonnet-4" color="blue" />

            {topLangs.length > 0 && (
              <>
                <div className="section-title">Languages</div>
                {topLangs.map(([name, bytes]) => (
                  <LangBar key={name} name={name} bytes={bytes} total={totalLangBytes} />
                ))}
              </>
            )}

            <div className="section-title">This session</div>
            <StatRow label="Messages" value={messages.length} />
            <StatRow label="AI responses" value={aiMessages} color="green" />
            <StatRow
              label="Tokens (est.)"
              value={`~${(tokenEstimate / 1000).toFixed(1)}k`}
            />
            <StatRow label="Files pinned" value={contextFiles.length} color="blue" />

            {meta?.description && (
              <>
                <div className="section-title">Description</div>
                <p style={{ fontSize: 11, color: "var(--text2)", lineHeight: 1.6 }}>
                  {meta.description}
                </p>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
