const GuacamoleLite = require("guacamole-lite");
const { createCallbacks } = require("./callbacks");

const port = Number.parseInt(process.env.PORT ?? "8080", 10);
const guacdHost = process.env.GUACD_HOST ?? "localhost";
const guacdPort = Number.parseInt(process.env.GUACD_PORT ?? "4822", 10);
const cryptKey = process.env.GUAC_CRYPT_KEY;

if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error("PORT must be a valid TCP port.");
}
if (!Number.isInteger(guacdPort) || guacdPort < 1 || guacdPort > 65535) {
  throw new Error("GUACD_PORT must be a valid TCP port.");
}
if (!cryptKey || Buffer.byteLength(cryptKey, "utf8") !== 32) {
  throw new Error("GUAC_CRYPT_KEY must be exactly 32 bytes.");
}

new GuacamoleLite(
  { port },
  { host: guacdHost, port: guacdPort },
  {
    crypt: {
      cypher: "AES-256-CBC",
      key: cryptKey,
    },
  },
  createCallbacks(),
);
