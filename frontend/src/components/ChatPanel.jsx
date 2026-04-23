import { useEffect, useRef, useState } from "react";

// Minimal markdown → HTML: bold, inline code, code blocks
function renderContent(text) {
  const blocks = [];
  const lines = text.split("\n");
  let i = 0;

  while (i < lines.length) {
    // Code block
    if (lines[i].startsWith("```")) {
      const lang = lines[i].slice(3).trim() || "code";
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      blocks.push({ type: "code", lang, content: codeLines.join("\n") });
      continue;
    }
    blocks.push({ type: "text", content: lines[i] });
    i++;
  }

  return blocks;
}

function inlineFormat(text) {
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, `<code style="font-family:var(--mono);font-size:11px;background:var(--bg);padding:1px 5px;border-radius:3px;">$1</code>`);
}

function CodeBlock({ lang, content }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="code-block">
      <div className="code-header">
        <span>{lang}</span>
        <button onClick={copy}>{copied ? "Copied!" : "Copy"}</button>
      </div>
      <pre>{content}</pre>
    </div>
  );
}

function Message({ msg }) {
  const blocks = renderContent(msg.content);
  return (
    <div className={`msg ${msg.role === "user" ? "user" : ""}`}>
      <div className={`avatar ${msg.role === "user" ? "user" : "ai"}`}>
        {msg.role === "user" ? "U" : "AI"}
      </div>
      <div className="bubble">
        {blocks.map((block, idx) =>
          block.type === "code" ? (
            <CodeBlock key={idx} lang={block.lang} content={block.content} />
          ) : (
            block.content.trim() && (
              <p
                key={idx}
                style={{ margin: "4px 0" }}
                dangerouslySetInnerHTML={{ __html: inlineFormat(block.content) }}
              />
            )
          )
        )}
        {msg.streaming && (
          <span style={{
            display: "inline-block", width: 8, height: 14,
            background: "var(--accent)", marginLeft: 2, verticalAlign: "middle",
            animation: "blink 0.8s infinite",
          }} />
        )}
      </div>
    </div>
  );
}

const HINTS = [
  "Add error handling to",
  "Write tests for",
  "Refactor",
  "Explain how",
  "Add type hints to",
  "Create a new endpoint for",
];

export default function ChatPanel({ messages, onSend, contextFiles, onRemoveContext, disabled }) {
  const [input, setInput] = useState("");
  const bottomRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = () => {
    const trimmed = input.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  const handleKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const autoResize = (e) => {
    e.target.style.height = "auto";
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px";
  };

  return (
    <div className="chat-area">
      {/* Context bar */}
      <div className="chat-context-bar">
        <span style={{ color: "var(--text3)" }}>Context:</span>
        {contextFiles.length === 0 && (
          <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "var(--mono)" }}>
            Click files in the tree to add context
          </span>
        )}
        {contextFiles.map(f => (
          <div key={f} className="ctx-tag">
            {f.split("/").pop()}
            <button onClick={() => onRemoveContext(f)}>✕</button>
          </div>
        ))}
        <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--text3)" }}>
          {contextFiles.length > 0 ? `${contextFiles.length} file${contextFiles.length > 1 ? "s" : ""} pinned` : ""}
        </span>
      </div>

      {/* Messages */}
      <div className="messages">
        {messages.length === 0 && (
          <div style={{ textAlign: "center", color: "var(--text3)", fontSize: 13, marginTop: 60 }}>
            Load a GitHub repository to get started
          </div>
        )}
        {messages.map((msg, i) => <Message key={i} msg={msg} />)}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="input-area">
        <div className="input-row">
          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            onChange={e => { setInput(e.target.value); autoResize(e); }}
            onKeyDown={handleKey}
            placeholder="Ask about the codebase, request a feature, or describe a bug…"
            disabled={disabled}
          />
          <button className="send-btn" onClick={send} disabled={disabled}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>
        <div className="input-hints">
          {HINTS.map(h => (
            <div key={h} className="hint-chip" onClick={() => setInput(h + " ")}>
              {h}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
