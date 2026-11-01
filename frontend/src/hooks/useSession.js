import { useState, useCallback, useRef } from "react";
import { loadRepo, streamChat, clearSession, getSessionUsage } from "../api/client";

export function useSession() {
  const [sessionId] = useState(() => crypto.randomUUID());
  const [repo, setRepo] = useState(null);       // LoadRepoResponse
  const [messages, setMessages] = useState([]); // { role, content }[]
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [contextFiles, setContextFiles] = useState([]);
  const [usage, setUsage] = useState(null);     // UsageStats for this session, from the backend
  const activeChatRequest = useRef(null);

  const load = useCallback(async (url) => {
    setLoading(true);
    setError(null);
    try {
      const data = await loadRepo(url, sessionId);
      setRepo(data);
      setMessages([{
        role: "assistant",
        content: `Repo loaded. Indexed **${data.file_count} files** from \`${data.meta.full_name}\`. What would you like to build?`,
      }]);
      return true;
    } catch (e) {
      setError(e.message);
      return false;
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  const chat = useCallback(async (prompt) => {
    if (!repo) return;
    const controller = new AbortController();
    activeChatRequest.current = controller;
    setMessages(prev => [...prev, { role: "user", content: prompt }]);

    // Append a streaming AI placeholder
    setMessages(prev => [...prev, { role: "assistant", content: "", streaming: true }]);

    try {
      await streamChat(sessionId, prompt, contextFiles, (token) => {
        setMessages(prev => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          updated[updated.length - 1] = { ...last, content: last.content + token };
          return updated;
        });
      }, controller.signal);
      setMessages(prev => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        updated[updated.length - 1] = { ...last, streaming: false };
        return updated;
      });
    } catch (e) {
      if (controller.signal.aborted) {
        setMessages(prev => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          updated[updated.length - 1] = { ...last, streaming: false, cancelled: true };
          return updated;
        });
      } else {
        setMessages(prev => [...prev.slice(0, -1), { role: "assistant", content: `Error: ${e.message}` }]);
      }
    } finally {
      if (activeChatRequest.current === controller) {
        activeChatRequest.current = null;
      }
    }
    // Usage is informational; a failure here shouldn't surface as a chat error.
    getSessionUsage(sessionId).then(setUsage).catch(() => {});
  }, [repo, sessionId, contextFiles]);

  const cancelChat = useCallback(() => {
    activeChatRequest.current?.abort();
  }, []);

  const addContextFile = useCallback((path) => {
    setContextFiles(prev => prev.includes(path) ? prev : [...prev, path]);
  }, []);

  const removeContextFile = useCallback((path) => {
    setContextFiles(prev => prev.filter(f => f !== path));
  }, []);

  const reset = useCallback(async () => {
    await clearSession(sessionId);
    setRepo(null);
    setMessages([]);
    setContextFiles([]);
    setUsage(null);
  }, [sessionId]);

  return {
    sessionId, repo, messages, loading, error, usage,
    contextFiles, addContextFile, removeContextFile,
    load, chat, cancelChat, reset,
  };
}
