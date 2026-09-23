/* Helper transport for the CutDeck panel. Connects to the CutDeck Python helper on
   ws://localhost:7891.

   Premiere can deny the socket on a cold start with "Permission denied to the url
   ws://localhost:<port>. Manifest entry not found." even though the manifest does
   declare the domain — UXP registers the plugin's network permission later than the
   panel's first request. The helper may also not be listening yet. Both failures land
   before the request is sent, so retrying them is safe.

   Retries stop the moment a request is sent. `prepare` mints a new job per call, so a
   blind resend could leave an orphan job behind; a lost reply is recovered through
   "Resume last job" instead, which the helper answers idempotently. */
(function (global) {
  const URL = "ws://localhost:7891";
  const ATTEMPTS = 5;
  const BACKOFF_MS = [200, 400, 800, 1600];
  const CONNECT_TIMEOUT_MS = 4000;
  const REPLY_TIMEOUT_MS = 15000;
  const UNREACHABLE = "Cannot reach CutDeck helper. Run Start CutDeck.cmd, then try again.";

  /* Resolves with an open socket, or rejects without having sent anything. */
  function open(createSocket, url, timeoutMs, setTimer, clearTimer) {
    return new Promise((resolve, reject) => {
      let socket = null;
      let settled = false;
      const done = (error) => {
        if (settled) return;
        settled = true;
        clearTimer(timer);
        if (socket) {
          socket.onopen = socket.onerror = socket.onclose = null;
          if (error) { try { socket.close(); } catch (_) { /* already closing */ } }
        }
        if (error) reject(error); else resolve(socket);
      };
      const timer = setTimer(() => done(new Error(UNREACHABLE)), timeoutMs);
      try {
        socket = createSocket(url);
      } catch (error) {
        // UXP throws the permission denial straight out of the constructor.
        done(error instanceof Error ? error : new Error(String(error)));
        return;
      }
      socket.onopen = () => done(null);
      socket.onerror = () => done(new Error(UNREACHABLE));
      socket.onclose = () => done(new Error(UNREACHABLE));
    });
  }

  /* Sends one request on an open socket. Never retried: the helper may have acted. */
  function exchange(socket, request, timeoutMs, setTimer, clearTimer) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const done = (error, result) => {
        if (settled) return;
        settled = true;
        clearTimer(timer);
        socket.onmessage = socket.onerror = socket.onclose = null;
        try { socket.close(); } catch (_) { /* already closing */ }
        if (error) reject(error); else resolve(result);
      };
      const timer = setTimer(
        () => done(new Error("CutDeck helper timed out. Start the helper and use Resume last job.")),
        timeoutMs);
      socket.onmessage = (event) => {
        try {
          const result = JSON.parse(event.data);
          done(result.ok ? null : new Error(result.message), result);
        } catch (error) { done(error); }
      };
      socket.onerror = () => done(new Error("Helper connection failed before it replied. Use Resume last job."));
      socket.onclose = () => done(new Error("Helper disconnected. Use Resume last job after reconnecting."));
      try {
        socket.send(JSON.stringify(request));
      } catch (error) { done(error instanceof Error ? error : new Error(String(error))); }
    });
  }

  function createRpc(options) {
    const opts = options || {};
    const createSocket = opts.createSocket || ((url) => new WebSocket(url));
    const setTimer = opts.setTimer || setTimeout;
    const clearTimer = opts.clearTimer || clearTimeout;
    const sleep = opts.sleep || ((ms) => new Promise((done) => setTimer(done, ms)));
    const onRetry = opts.onRetry || (() => {});
    const url = opts.url || URL;
    const attempts = opts.attempts || ATTEMPTS;
    const backoff = opts.backoff || BACKOFF_MS;

    return async function rpc(request) {
      let failure;
      for (let attempt = 0; attempt < attempts; attempt++) {
        if (attempt) {
          onRetry(attempt + 1, attempts, failure);
          await sleep(backoff[Math.min(attempt - 1, backoff.length - 1)]);
        }
        let socket;
        try {
          socket = await open(createSocket, url, opts.connectTimeoutMs || CONNECT_TIMEOUT_MS,
            setTimer, clearTimer);
        } catch (error) {
          failure = error;
          continue;
        }
        return exchange(socket, request, opts.replyTimeoutMs || REPLY_TIMEOUT_MS,
          setTimer, clearTimer);
      }
      throw failure;
    };
  }

  const exportObj = { createRpc, URL, ATTEMPTS, UNREACHABLE };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = exportObj;
  }
  if (global) {
    global.CutDeckRpc = exportObj;
  }
})(typeof window !== "undefined" ? window : globalThis);
