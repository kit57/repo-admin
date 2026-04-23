import { useState } from "react";
import FileTree from "./components/FileTree";
import ChatPanel from "./components/ChatPanel";
import InfoPanel from "./components/InfoPanel";
import { useSession } from "./hooks/useSession";

export default function App() {
  const {
    repo, messages, loading, error,
    contextFiles, addContextFile, removeContextFile,
    load, chat,
  } = useSession();

  const [repoUrl, setRepoUrl] = useState("");
  const [activeFile, setActiveFile] = useState(null);

  const handleLoad = (e) => {
    e.preventDefault();
    if (repoUrl.trim()) load(repoUrl.trim());
  };

  const handleFileSelect = (path) => {
    setActiveFile(path);
    addContextFile(path);
  };

  const isStreaming = messages.some(m => m.streaming);

  return (
    <>
      {/* Top bar */}
      <div className="topbar">
        <div className="logo">Repo<span>AI</span></div>
        <form onSubmit={handleLoad} style={{ display: "flex", gap: 8, flex: 1, maxWidth: 560 }}>
          <div className="repo-input-wrap" style={{ flex: 1 }}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4" />
              <path d="M9 18c-4.51 2-5-2-7-2" />
            </svg>
            <input
              type="text"
              placeholder="https://github.com/owner/repository"
              value={repoUrl}
              onChange={e => setRepoUrl(e.target.value)}
            />
          </div>
          <button className="load-btn" type="submit" disabled={loading}>
            {loading ? "Loading…" : "Load"}
          </button>
        </form>

        <div className="status-badge">
          {repo ? (
            <>
              <div className="dot" />
              indexed · {repo.file_count?.toLocaleString()} files
            </>
          ) : error ? (
            <span style={{ color: "#f87171", fontSize: 11 }}>⚠ {error}</span>
          ) : (
            <span style={{ color: "var(--text3)", fontSize: 11 }}>no repo loaded</span>
          )}
        </div>
      </div>

      {/* Main layout */}
      <div className="main">
        <FileTree
          tree={repo?.tree || []}
          onSelect={handleFileSelect}
          activeFile={activeFile}
        />
        <ChatPanel
          messages={messages}
          onSend={chat}
          contextFiles={contextFiles}
          onRemoveContext={removeContextFile}
          disabled={!repo || isStreaming}
        />
        <InfoPanel
          repo={repo}
          messages={messages}
          contextFiles={contextFiles}
        />
      </div>
    </>
  );
}
