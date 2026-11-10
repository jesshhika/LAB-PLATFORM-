const test = require("node:test");
const assert = require("node:assert/strict");
const { getLaunchErrorMessage } = require("./launch-error.js");

test("launch throttling displays the capacity guidance", () => {
  assert.equal(
    getLaunchErrorMessage(429),
    "Lab capacity reached, try again later",
  );
});

test("other launch failures retain their HTTP status", () => {
  assert.equal(getLaunchErrorMessage(503), "Could not launch lab (HTTP 503).");
});
