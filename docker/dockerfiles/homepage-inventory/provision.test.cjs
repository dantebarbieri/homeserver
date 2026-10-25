const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");
const YAML = require("yaml");
const { atomicWrite, credential, provision, putCredential } = require("./provision.cjs");

test("credentials are generated safely, preserved on rerun and never silently accept a template", () => {
  const value = credential("", "HOMEPAGE_WIDGET_DB_PASSWORD");
  assert.match(value, /^[A-Za-z0-9_-]{43}$/);
  assert.equal(credential(`HOMEPAGE_WIDGET_DB_PASSWORD='${value}'`, "HOMEPAGE_WIDGET_DB_PASSWORD"), value);
  assert.throws(() => credential("HOMEPAGE_WIDGET_DB_PASSWORD=bad", "HOMEPAGE_WIDGET_DB_PASSWORD"), /Invalid/);
  const duplicate = `HOMEPAGE_WIDGET_DB_PASSWORD=${value}\nHOMEPAGE_WIDGET_DB_PASSWORD=${value}\n`;
  assert.throws(() => credential(duplicate, "HOMEPAGE_WIDGET_DB_PASSWORD"), /Duplicate/);
  assert.throws(() => putCredential(duplicate, "HOMEPAGE_WIDGET_DB_PASSWORD", value), /Duplicate/);
  assert.equal(putCredential("EXISTING=private\n", "NEW_KEY", "new"), "EXISTING=private\nNEW_KEY=new\n");
});

test("a failed atomic rename preserves the original and removes only its own temporary file", (t) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "homepage-provision-"));
  t.after(() => fs.rmSync(directory, { recursive: true }));
  const filename = path.join(directory, ".env");
  fs.writeFileSync(filename, "original");
  t.mock.method(fs, "renameSync", () => { throw new Error("Rename failed"); });
  assert.throws(() => atomicWrite(filename, "replacement"), /Rename failed/);
  assert.equal(fs.readFileSync(filename, "utf8"), "original");
  assert.deepEqual(fs.readdirSync(directory), [".env"]);
});

test("provisioning preserves config values/comments and existing metrics authentication without enabling telemetry", (t) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "homepage-provision-"));
  t.after(() => fs.rmSync(directory, { recursive: true }));
  const envPath = path.join(directory, ".env");
  const settingsPath = path.join(directory, "settings.yml");
  fs.writeFileSync(envPath, "UNCHANGED=private\n", { mode: 0o600 });
  fs.writeFileSync(settingsPath, '# retain this comment\ngeneral:\n  open_metrics: "existing-metrics-password"\nserver:\n  secret_key: private\n');
  const password = provision(envPath, settingsPath);
  assert.equal(provision(envPath, settingsPath), password);
  const env = fs.readFileSync(envPath, "utf8");
  assert.ok(env.startsWith("UNCHANGED=private\n"));
  assert.ok(env.includes("HOMEPAGE_SEARXNG_METRICS_PASSWORD='existing-metrics-password'"));
  const text = fs.readFileSync(settingsPath, "utf8");
  assert.ok(text.includes("# retain this comment"));
  assert.deepEqual(YAML.parse(text), {
    general: { open_metrics: "existing-metrics-password" }, server: { secret_key: "private" },
  });
  fs.writeFileSync(settingsPath, "general:\n  enable_metrics: false\n");
  assert.throws(() => provision(envPath, settingsPath), /refusing to enable tracking/);
  assert.equal(fs.readFileSync(envPath, "utf8"), env);
});
