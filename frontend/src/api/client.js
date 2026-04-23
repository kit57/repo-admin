const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function loadRepo(url, sessionId) {
  const res = await fetch(`${BASE}/repo/load`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, session_id: sessionId, max_files: 300 }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to load repo");
  }
  return res.json();
}

export async function getTree(sessionId) {
  const res = await fetch(`${BASE}/repo/tree/${sessionId}`);
  if (!res.ok) throw new Error("Failed to fetch tree");
  return res.json();
}

/**
 * Stream a chat response. Calls onToken for each streamed chunk.
 * Returns the full response string.
 */
export async function streamChat(sessionId, prompt, contextFiles, onToken) {
  const res = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      prompt,
      context_files: contextFiles,
    }),
  });

  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Chat request failed");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let full = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value, { stream: true });
    full += chunk;
    onToken(chunk);
  }

  return full;
}

export async function clearSession(sessionId) {
  await fetch(`${BASE}/session/${sessionId}`, { method: "DELETE" });
}