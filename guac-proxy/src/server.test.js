const test = require("node:test");
const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const path = require("node:path");
const { createCallbacks } = require("./callbacks");

test("proxy rejects a missing encryption key", () => {
  const result = spawnSync(process.execPath, [path.join(__dirname, "server.js")], {
    env: { ...process.env, GUAC_CRYPT_KEY: "" },
    encoding: "utf8",
  });

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /GUAC_CRYPT_KEY must be exactly 32 bytes/);
});

test("proxy validates token expiration and logs session lifecycle", async () => {
  const events = [];
  const callbacks = createCallbacks((event) => events.push(event));
  const settings = {
    expiration: Date.now() + 60_000,
    session_id: "session-123",
    connection: { settings: { hostname: "10.50.16.4" } },
  };

  callbacks.processConnectionSettings(settings, (error, validated) => {
    assert.ifError(error);
    assert.equal(validated, settings);
  });
  await callbacks.sessionRegistry.set("guac-session", {
    connectionInfo: { settings: { hostname: "10.50.16.4" } },
  });
  await callbacks.sessionRegistry.delete("guac-session");

  assert.deepEqual(events, [
    { event: "connected", session_id: "session-123" },
    { event: "disconnected", session_id: "session-123" },
  ]);
});

test("proxy rejects expired connection tokens", () => {
  const callbacks = createCallbacks(() => {});
  callbacks.processConnectionSettings(
    {
      expiration: Date.now() - 1,
      session_id: "session-123",
      connection: { settings: { hostname: "10.50.16.4" } },
    },
    (error) => assert.match(error.message, /expired/),
  );
});

test("proxy rejects non-private VM addresses", () => {
  const callbacks = createCallbacks(() => {});
  callbacks.processConnectionSettings(
    {
      expiration: Date.now() + 60_000,
      session_id: "session-123",
      connection: { settings: { hostname: "8.8.8.8" } },
    },
    (error) => assert.match(error.message, /private IPv4/),
  );
});
