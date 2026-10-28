import { Children, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

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

function MarkdownCodeBlock({ children }) {
  const code = Children.toArray(children).find(child => child.type === "code");
  const language = code?.props.className?.match(/language-([\w-]+)/)?.[1] || "code";
  const content = String(code?.props.children ?? "").replace(/\n$/, "");
  return <CodeBlock lang={language} content={content} />;
}

const MARKDOWN_COMPONENTS = {
  a: ({ href, children, ...props }) => href
    ? <a {...props} href={href} target="_blank" rel="noreferrer noopener">{children}</a>
    : <>{children}</>,
  pre: MarkdownCodeBlock,
};

function Message({ msg }) {
  return (
    <div className={`msg ${msg.role === "user" ? "user" : ""}`}>
      <div className={`avatar ${msg.role === "user" ? "user" : "ai"}`}>
        {msg.role === "user" ? "U" : "AI"}
      </div>
      <div className="bubble">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
          {msg.content}
        </ReactMarkdown>
        {msg.streaming && (
          <span style={{
            display: "inline-block", width: 8, height: 14,
            background: "var(--accent)", marginLeft: 2, verticalAlign: "middle",
            animation: "blink 0.8s infinite",
          }} />
        )}
        {msg.cancelled && <div className="generation-cancelled">Generation cancelled.</div>}
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

export default function ChatPanel({ messages, onSend, onCancel, contextFiles, onRemoveContext, disabled }) {
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
          {messages.some(message => message.streaming) ? (
            <button
              className="cancel-btn"
              onClick={onCancel}
              type="button"
              aria-label="Cancel generation"
              title="Cancel generation"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <rect x="6" y="5" width="4" height="14" rx="1" />
                <rect x="14" y="5" width="4" height="14" rx="1" />
              </svg>
            </button>
          ) : (
            <button className="send-btn" onClick={send} disabled={disabled} type="button" aria-label="Send message">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          )}
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
