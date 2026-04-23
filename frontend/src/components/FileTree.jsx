import { useState, useMemo } from "react";

const FOLDER_ICONS = { src: "📁", tests: "🧪", docs: "📚", default: "📁" };
const FILE_ICONS = {
  ".py": "🐍", ".js": "📜", ".ts": "📘", ".tsx": "⚛️", ".jsx": "⚛️",
  ".md": "📄", ".json": "🔧", ".yaml": "⚙️", ".yml": "⚙️",
  ".toml": "⚙️", ".sh": "💻", ".css": "🎨", ".html": "🌐",
};

function getFileIcon(path) {
  const ext = "." + path.split(".").pop();
  return FILE_ICONS[ext] || "📄";
}

function buildTree(nodes) {
  const root = {};
  for (const node of nodes) {
    const parts = node.path.split("/");
    let cur = root;
    for (let i = 0; i < parts.length - 1; i++) {
      if (!cur[parts[i]]) cur[parts[i]] = { __children: {} };
      cur = cur[parts[i]].__children;
    }
    const file = parts[parts.length - 1];
    cur[file] = { __leaf: true, path: node.path, size: node.size };
  }
  return root;
}

function TreeNode({ name, node, depth = 0, onSelect, activeFile }) {
  const [open, setOpen] = useState(depth < 2);

  if (node.__leaf) {
    const active = activeFile === node.path;
    return (
      <div
        className={`tree-item ${active ? "active" : ""}`}
        style={{ paddingLeft: 14 + depth * 12 }}
        onClick={() => onSelect(node.path)}
      >
        <span className="tree-icon">{getFileIcon(name)}</span>
        {name}
      </div>
    );
  }

  const children = Object.entries(node.__children || node);
  return (
    <>
      <div
        className="tree-item folder"
        style={{ paddingLeft: 14 + depth * 12 }}
        onClick={() => setOpen(o => !o)}
      >
        <span style={{ fontSize: 10, color: "var(--accent2)", marginRight: 4 }}>
          {open ? "▾" : "▸"}
        </span>
        <span className="tree-icon">
          {FOLDER_ICONS[name.toLowerCase()] || FOLDER_ICONS.default}
        </span>
        {name}
      </div>
      {open && children.map(([childName, childNode]) => (
        <TreeNode
          key={childName}
          name={childName}
          node={childNode}
          depth={depth + 1}
          onSelect={onSelect}
          activeFile={activeFile}
        />
      ))}
    </>
  );
}

export default function FileTree({ tree = [], onSelect, activeFile }) {
  const [filter, setFilter] = useState("");

  const filtered = useMemo(() => {
    if (!filter) return tree;
    return tree.filter(n => n.path.toLowerCase().includes(filter.toLowerCase()));
  }, [tree, filter]);

  const treeData = useMemo(() => buildTree(filtered), [filtered]);

  return (
    <div className="sidebar">
      <div className="sidebar-header">File Explorer</div>
      <div style={{ padding: "8px 10px", borderBottom: "1px solid var(--border)" }}>
        <input
          type="text"
          placeholder="Filter files…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          style={{
            width: "100%", background: "var(--bg3)", border: "1px solid var(--border2)",
            borderRadius: "var(--radius)", padding: "5px 8px", color: "var(--text)",
            fontFamily: "var(--mono)", fontSize: 11, outline: "none",
          }}
        />
      </div>
      <div className="file-tree">
        {Object.entries(treeData).map(([name, node]) => (
          <TreeNode key={name} name={name} node={node} onSelect={onSelect} activeFile={activeFile} />
        ))}
        {filtered.length === 0 && (
          <div style={{ padding: "16px 14px", color: "var(--text3)", fontSize: 11, fontFamily: "var(--mono)" }}>
            No files match
          </div>
        )}
      </div>
    </div>
  );
}
