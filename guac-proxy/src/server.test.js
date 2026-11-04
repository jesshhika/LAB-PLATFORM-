const test = require("node:test");
const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const path = require("node:path");

test("proxy rejects a missing encryption key", () => {
  const result = spawnSync(process.execPath, [path.join(__dirname, "server.js")], {
    env: { ...process.env, GUAC_CRYPT_KEY: "" },
    encoding: "utf8",
  });

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /GUAC_CRYPT_KEY must be exactly 32 bytes/);
});
