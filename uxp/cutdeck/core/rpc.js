/* Helper transport for the CutDeck panel. Connects to the CutDeck Python helper on
   ws://localhost:7891 (protocol v2, docs/arch-design-helper-v2.md).

   Premiere can deny the socket on a cold start with "Permission denied to the url
   ws://localhost:<port>. Manifest entry not found." even though the manifest does
   declare the domain — UXP registers the plugin's network permission later than the
   panel's first request. The helper may also not be listening yet. Both failures land
   before the request is sent, so retrying them is safe.

   Retries stop the moment a request is sent. `prepare` mints a new job per call, so a
   blind resend could leave an orphan job behind; a lost reply is recovered through
   "Resume last job" instead, which the helper answers idempotently.

   One connection is kept open between calls. Every request carries an `id` and the helper
   echoes it, so calls go out together and each reply finds its caller even out of order.
   The same socket also carries what the helper sends unasked:
     {"event": "job", "job": …}  a watched job's progress (`rpc.watch`), instead of polling;
     {"call": …, "command", "args"}  a Premiere command for this panel to run (`onCall`),
                                     answered with {"type": "driver_reply", "call", ok, …}.

   UXP APIs: WebSocket send/close/readyState (reference/adobe/api/uxp.txt:3157-3164); the
   onopen/onmessage/onerror/onclose handlers (Adobe's network recipe,
   reference/adobe/docs/resources/recipes/network/index.md:258-271). */
(function (global) {
  const URL = "ws://localhost:7891";
  const ATTEMPTS = 5;
  const BACKOFF_MS = [200, 400, 800, 1600];
  const CONNECT_TIMEOUT_MS = 4000;
  const REPLY_TIMEOUT_MS = 15000;
  const UNREACHABLE = "Cannot reach CutDeck helper. Run Start CutDeck.cmd, then try again.";
  const DISCONNECTED = "Helper disconnected. Use Resume last job after reconnecting.";
  const TERMINAL = new Set(["ready", "no_cuts", "failed", "interrupted"]);

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

  function createRpc(options) {
    const opts = options || {};
    const createSocket = opts.createSocket || ((url) => new WebSocket(url));
    const setTimer = opts.setTimer || setTimeout;
    const clearTimer = opts.clearTimer || clearTimeout;
    const sleep = opts.sleep || ((ms) => new Promise((done) => setTimer(done, ms)));
    const onRetry = opts.onRetry || (() => {});
    const onClose = opts.onClose || (() => {});
    const url = opts.url || URL;
    const attempts = opts.attempts || ATTEMPTS;
    const backoff = opts.backoff || BACKOFF_MS;

    let socket = null;       // the open connection, shared by every call
    let connecting = null;   // the attempt in flight, so overlapping calls open one socket
    let nextId = 1;
    const pending = new Map();   // id -> { resolve, reject, timer }
    const watchers = new Map();  // job_id -> Set of { update, fail }

    function settle(id, message) {
      const entry = pending.get(id);
      if (!entry) return;
      pending.delete(id);
      clearTimer(entry.timer);
      const { id: _, ...result } = message;
      // `code` lets callers branch on the failure kind without matching its wording.
      if (result.ok) entry.resolve(result);
      else entry.reject(Object.assign(new Error(result.message), { code: result.code }));
    }

    function answerCall(from, call) {
      const reply = (fields) => {
        try { from.send(JSON.stringify({ type: "driver_reply", call: call.call, ...fields })); }
        catch (_) { /* gone: the helper fails the call itself on disconnect */ }
      };
      Promise.resolve()
        .then(() => {
          if (!opts.onCall) throw new Error("This connection does not run Premiere commands");
          return opts.onCall(call);
        })
        .then((result) => reply({ ok: true, result: result === undefined ? null : result }),
          (error) => reply({ ok: false, message: (error && error.message) || String(error) }));
    }

    function receive(from, event) {
      let message;
      try { message = JSON.parse(event.data); } catch (_) { return; }
      if (message.event === "job" && message.job) {
        for (const w of [...(watchers.get(message.job.job_id) || [])]) w.update(message.job);
      } else if (message.call !== undefined) {
        answerCall(from, message);
      } else if (message.id !== undefined) {
        settle(message.id, message);
      } else if (pending.size) {
        // A helper from before protocol v2 answers in order and echoes no id (an old helper
        // refusing `hello` must still be recognised, so it can be restarted).
        settle(pending.keys().next().value, message);
      }
    }

    function drop(closed, reason) {
      if (socket !== closed) return;
      socket = null;
      closed.onmessage = closed.onerror = closed.onclose = null;
      try { closed.close(); } catch (_) { /* already closing */ }
      for (const id of [...pending.keys()]) settle(id, { ok: false, message: reason });
      for (const set of watchers.values()) for (const w of [...set]) w.fail(new Error(reason));
      onClose();
    }

    function adopt(opened) {
      socket = opened;
      opened.onmessage = (event) => receive(opened, event);
      opened.onerror = () => drop(opened, "Helper connection failed before it replied. Use Resume last job.");
      opened.onclose = () => drop(opened, DISCONNECTED);
      return opened;
    }

    async function connect() {
      let failure;
      for (let attempt = 0; attempt < attempts; attempt++) {
        if (attempt) {
          onRetry(attempt + 1, attempts, failure);
          await sleep(backoff[Math.min(attempt - 1, backoff.length - 1)]);
        }
        try {
          return adopt(await open(createSocket, url, opts.connectTimeoutMs || CONNECT_TIMEOUT_MS,
            setTimer, clearTimer));
        } catch (error) {
          failure = error;
        }
      }
      throw failure;
    }

    function ready() {
      // readyState 1 = OPEN (reference/adobe/api/uxp.txt WebSocket.readyState).
      if (socket && (socket.readyState === undefined || socket.readyState === 1)) return Promise.resolve(socket);
      if (socket) drop(socket, DISCONNECTED);
      if (!connecting) connecting = connect().finally(() => { connecting = null; });
      return connecting;
    }

    async function rpc(request) {
      const to = await ready();
      const id = nextId++;
      return new Promise((resolve, reject) => {
        const timer = setTimer(() => settle(id, { ok: false,
          message: "CutDeck helper timed out. Start the helper and use Resume last job." }),
          opts.replyTimeoutMs || REPLY_TIMEOUT_MS);
        pending.set(id, { resolve, reject, timer });
        try {
          to.send(JSON.stringify({ ...request, id }));
        } catch (error) {
          settle(id, { ok: false, message: (error && error.message) || String(error) });
        }
      });
    }

    /* Resolves with the job once it has finished (ready, no_cuts, failed or interrupted);
       `onUpdate(job)` sees every state on the way. Rejects if the helper connection drops. */
    rpc.watch = function watch(jobId, onUpdate) {
      return new Promise((resolve, reject) => {
        let settled = false;
        const set = watchers.get(jobId) || new Set();
        watchers.set(jobId, set);
        const finish = () => {
          settled = true;
          set.delete(entry);
          if (!set.size && watchers.get(jobId) === set) watchers.delete(jobId);
        };
        const entry = {
          update(job) {
            if (settled) return;
            if (onUpdate) onUpdate(job);
            if (TERMINAL.has(job.state)) { finish(); resolve(job); }
          },
          fail(error) { if (!settled) { finish(); reject(error); } },
        };
        set.add(entry);
        rpc({ type: "watch", job_id: jobId })
          .then(({ ok: _, ...job }) => entry.update(job), (error) => entry.fail(error));
      });
    };

    return rpc;
  }

  const exportObj = { createRpc, URL, ATTEMPTS, UNREACHABLE, TERMINAL };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = exportObj;
  }
  if (global) {
    global.CutDeckRpc = exportObj;
  }
})(typeof window !== "undefined" ? window : globalThis);
