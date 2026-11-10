const net = require("node:net");

function isPrivateIpv4(value) {
  if (!net.isIPv4(value)) return false;
  const [first, second] = value.split(".").map(Number);
  return first === 10
    || (first === 172 && second >= 16 && second <= 31)
    || (first === 192 && second === 168);
}

function createCallbacks(log = (entry) => console.info(JSON.stringify(entry))) {
  const sessions = new Map();
  const sessionIdsByHost = new Map();
  const loggedConnections = new Set();

  const callbacks = {
    processConnectionSettings(settings, callback) {
      const sessionId = settings.session_id;
      if (typeof sessionId !== "string" || sessionId.length === 0) {
        return callback(new Error("Connection token is missing its session ID."));
      }
      if (!Number.isFinite(settings.expiration) || settings.expiration <= Date.now()) {
        log({ event: "connection_rejected", session_id: sessionId, reason: "expired_token" });
        return callback(new Error("Connection token has expired."));
      }

      const host = settings.connection?.settings?.hostname;
      if (typeof host !== "string" || !isPrivateIpv4(host)) {
        return callback(new Error("Connection token must target a private IPv4 address."));
      }

      sessionIdsByHost.set(host, sessionId);
      callback(null, settings);
    },
    sessionRegistry: {
      async get(sessionKey) {
        return sessions.get(sessionKey);
      },
      async set(sessionKey, sessionData) {
        sessions.set(sessionKey, sessionData);
        const host = sessionData.connectionInfo?.settings?.hostname;
        const sessionId = typeof host === "string" ? sessionIdsByHost.get(host) : undefined;
        if (sessionId && !loggedConnections.has(sessionKey)) {
          loggedConnections.add(sessionKey);
          log({ event: "connected", session_id: sessionId });
        }
      },
      async delete(sessionKey) {
        const sessionData = sessions.get(sessionKey);
        const host = sessionData?.connectionInfo?.settings?.hostname;
        const sessionId = typeof host === "string" ? sessionIdsByHost.get(host) : undefined;
        sessions.delete(sessionKey);
        if (sessionId && loggedConnections.delete(sessionKey)) {
          log({ event: "disconnected", session_id: sessionId });
        }
        if (typeof host === "string" && sessionIdsByHost.get(host) === sessionId) {
          sessionIdsByHost.delete(host);
        }
      },
    },
  };

  return callbacks;
}

module.exports = { createCallbacks, isPrivateIpv4 };
