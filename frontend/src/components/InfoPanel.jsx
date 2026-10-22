import { useMemo } from "react";
import { timeSince } from "../utils/time";

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

const kTokens = (n) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`);

function formatTokens(usage) {
  if (!usage?.calls) return "—";
  const input = usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens;
  const prefix = usage.estimated_calls ? "~" : "";
  return `${prefix}${kTokens(input)} / ${kTokens(usage.output_tokens)}`;
}

function formatCost(usage) {
  if (!usage?.calls) return "—";
  if (usage.unpriced_calls === usage.calls) return "n/a (no price set)";
  const cost = `$${usage.cost_usd.toFixed(usage.cost_usd < 0.01 ? 4 : 2)}`;
  return usage.unpriced_calls ? `${cost} + unpriced` : cost;
}

export default function InfoPanel({ repo, messages, contextFiles, usage }) {
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
            <StatRow label="Provider" value={repo.provider} />
            <StatRow label="Model" value={repo.model?.replace(/^claude-/, "")} color="blue" />

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
            <StatRow label="Tokens in / out" value={formatTokens(usage)} />
            <StatRow label="Cost" value={formatCost(usage)} color="green" />
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
