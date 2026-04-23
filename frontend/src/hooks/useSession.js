import { useState, useCallback } from "react";
import { loadRepo, streamChat, clearSession } from "../api/client";

export function useSession() {
  const [sessionId] = useState(() => crypto.randomUUID());
  const [repo, setRepo] = useState(null);       // LoadRepoResponse
  const [messages, setMessages] = useState([]); // { role, content }[]
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [contextFiles, setContextFiles] = useState([]);

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
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  const chat = useCallback(async (prompt) => {
    if (!repo) return;
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
      });
      // Mark streaming done
      setMessages(prev => {
        const updated = [...prev];
        updated[updated.length - 1] = { ...updated[updated.length - 1], streaming: false };
        return updated;
      });
    } catch (e) {
      setMessages(prev => [...prev.slice(0, -1), { role: "assistant", content: `Error: ${e.message}` }]);
    }
  }, [repo, sessionId, contextFiles]);

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
  }, [sessionId]);

  return {
    sessionId, repo, messages, loading, error,
    contextFiles, addContextFile, removeContextFile,
    load, chat, reset,
  };
}
