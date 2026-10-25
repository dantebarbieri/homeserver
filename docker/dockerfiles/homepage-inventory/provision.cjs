const fs = require("node:fs");
const crypto = require("node:crypto");
const YAML = require("yaml");

function credentialLine(env, name) {
  const matches = [...env.matchAll(new RegExp(`^${name}=(.*)$`, "gm"))];
  if (matches.length > 1) throw new Error("Duplicate widget credential");
  return matches[0];
}

function credential(env, name) {
  const match = credentialLine(env, name);
  if (!match || !match[1].trim()) return crypto.randomBytes(32).toString("base64url");
  const value = match[1].trim().replace(/^(['"])(.*)\1$/, "$2");
  if (!/^[A-Za-z0-9_-]{32,128}$/.test(value)) throw new Error("Invalid widget credential");
  return value;
}

function putCredential(env, name, value) {
  credentialLine(env, name);
  const line = new RegExp(`^${name}=.*$`, "m");
  if (line.test(env)) return env.replace(line, `${name}=${value}`);
  return `${env}${env.endsWith("\n") ? "" : "\n"}${name}=${value}\n`;
}

function atomicWrite(filename, content) {
  const stat = fs.statSync(filename);
  const temporary = `${filename}.homepage-widget-tmp`;
  const descriptor = fs.openSync(temporary, "wx", 0o600);
  try {
    try {
      fs.writeFileSync(descriptor, content);
      fs.fchmodSync(descriptor, stat.mode & 0o777);
      fs.fchownSync(descriptor, stat.uid, stat.gid);
      fs.fsyncSync(descriptor);
    } finally {
      fs.closeSync(descriptor);
    }
    fs.renameSync(temporary, filename);
  } catch (error) {
    fs.unlinkSync(temporary);
    throw error;
  }
}

function provision(envPath, settingsPath) {
  let env = fs.readFileSync(envPath, "utf8");
  const document = YAML.parseDocument(fs.readFileSync(settingsPath, "utf8"));
  if (document.errors.length) throw new Error("Invalid SearXNG settings");
  const enabled = document.getIn(["general", "enable_metrics"]);
  if (enabled === false) throw new Error("SearXNG metrics are disabled; refusing to enable tracking");
  const existing = document.getIn(["general", "open_metrics"]);
  const password = credential(env, "HOMEPAGE_WIDGET_DB_PASSWORD");
  const metricsPassword = existing || credential(env, "HOMEPAGE_SEARXNG_METRICS_PASSWORD");
  if (typeof metricsPassword !== "string" || /[\r\n]/.test(metricsPassword)) throw new Error("Invalid metrics credential");
  env = putCredential(env, "HOMEPAGE_WIDGET_DB_PASSWORD", password);
  env = putCredential(env, "HOMEPAGE_SEARXNG_METRICS_PASSWORD", `'${metricsPassword.replace(/'/g, "\\'")}'`);
  document.setIn(["general", "open_metrics"], metricsPassword);
  atomicWrite(envPath, env);
  atomicWrite(settingsPath, document.toString());
  return password;
}

if (require.main === module) {
  try {
    if (process.argv[2] === "--password") {
      const env = fs.readFileSync("/configuration/.env", "utf8");
      process.stdout.write(credential(env, "HOMEPAGE_WIDGET_DB_PASSWORD"));
    } else {
      provision("/configuration/.env", "/settings/settings.yml");
      console.log("Widget credentials and protected local SearXNG metrics configured");
    }
  } catch {
    console.error("Widget provisioning failed; check configuration permissions and credential format before rerunning");
    process.exitCode = 1;
  }
}

module.exports = { atomicWrite, credential, provision, putCredential };
