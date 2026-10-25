const http = require("node:http");
const path = require("node:path");
const { databaseFiles, readStats } = require("./stats.cjs");

const appVersionLabels = new Set([
  "adguardhome", "audiobookshelf", "aurral", "authelia", "bazarr", "bookbridge",
  "calibre-web", "changedetection-io", "code-server", "convertx", "coturn", "dashdot",
  "ddclient", "element", "endlessh", "flaresolverr", "forgejo", "forgejo_runner",
  "homepage", "immich_machine_learning", "immich_server", "librofm-downloader",
  "lidarr", "livekit", "lk-jwt-service", "mcp-tcad", "ntfy", "plex", "prowlarr",
  "qbit-manage", "qbittorrent-app", "radarr", "recyclarr", "romm", "sabnzbd",
  "searxng", "seerr", "slskd", "snapotter", "sonarr", "stirling-pdf", "suwayomi",
  "synapse", "syncthing", "tdarr", "vaultwarden",
]);
const appRevisionSources = {
  soularr: "https://github.com/mrusse/soularr",
  mirklurk: "https://github.com/dantebarbieri/mirklurk-wiki",
  "mirklurk-map": "https://github.com/dantebarbieri/mirklurk-map",
  "mirklurk-map-uploads": "https://github.com/dantebarbieri/mirklurk-map",
};
const versionFiles = {
  "wg-easy": {
    path: "/app/package.json",
    parse: (text) => JSON.parse(text).release?.version,
    prefix: "v",
  },
  "satisfactory-server": {
    path: "/config/gamefiles/steamapps/appmanifest_1690800.acf",
    parse: (text) => text.match(/"buildid"\s+"(\d+)"/)?.[1],
    prefix: "Steam build ",
  },
};

class InventoryError extends Error {
  constructor(message, status = 502) {
    super(message);
    this.status = status;
  }
}

function dockerRequest(socketPath, requestPath, { binary = false, timeoutMs = 5000 } = {}) {
  return new Promise((resolve, reject) => {
    const request = http.get({ socketPath, path: requestPath }, (response) => {
      const chunks = [];
      let size = 0;
      response.on("data", (chunk) => {
        size += chunk.length;
        if (size > 2 * 1024 * 1024) {
          request.destroy(new InventoryError("Docker response exceeded the size limit"));
          return;
        }
        chunks.push(chunk);
      });
      response.on("error", () => reject(new InventoryError("Docker response interrupted")));
      response.on("end", () => {
        if (response.statusCode === 404) return reject(new InventoryError("Container or image not found", 404));
        if (response.statusCode !== 200) return reject(new InventoryError("Docker request failed"));
        const body = Buffer.concat(chunks);
        if (binary) return resolve(body);
        try {
          resolve(JSON.parse(body.toString("utf8")));
        } catch {
          reject(new InventoryError("Docker returned invalid JSON"));
        }
      });
    });
    request.setTimeout(timeoutMs, () => request.destroy(new InventoryError("Docker request timed out", 504)));
    request.on("error", (error) => reject(
      error instanceof InventoryError ? error : new InventoryError("Docker socket unavailable"),
    ));
  });
}

function archiveText(buffer, filename) {
  for (let offset = 0; offset + 512 <= buffer.length;) {
    const header = buffer.subarray(offset, offset + 512);
    if (header.every((byte) => byte === 0)) break;
    const sizeText = header.toString("ascii", 124, 136).replace(/\0.*$/, "").trim();
    if (!/^[0-7]+$/.test(sizeText)) throw new InventoryError("Invalid version-file archive");
    const size = parseInt(sizeText, 8);
    const start = offset + 512;
    if (start + size > buffer.length) throw new InventoryError("Truncated version-file archive");
    const name = header.toString("utf8", 0, 100).replace(/\0.*$/, "");
    const type = header[156];
    if ((type === 0 || type === 48) && name === filename) {
      return buffer.toString("utf8", start, start + size);
    }
    offset = start + Math.ceil(size / 512) * 512;
  }
  throw new InventoryError("Version file missing from archive");
}

function validVersion(value) {
  return typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._+:/()-]{0,95}$/.test(value);
}

function imageVersion(name, image) {
  const config = image.Config || {};
  const environment = Object.fromEntries((config.Env || []).map((entry) => {
    const separator = entry.indexOf("=");
    return [entry.slice(0, separator), entry.slice(separator + 1)];
  }));
  const envKey = name.endsWith("_postgres") ? "PG_VERSION"
    : name.endsWith("_redis") && name !== "searxng_redis" ? "REDIS_VERSION"
      : { couchdb: "COUCHDB_VERSION", nginxproxymanager: "NPM_BUILD_VERSION",
        nextcloud_cron: "NEXTCLOUD_VERSION", forgejo_runner_dind: "DOCKER_VERSION" }[name];
  if (envKey && environment[envKey] !== undefined) {
    if (!validVersion(environment[envKey])) throw new InventoryError("Invalid application version metadata");
    return environment[envKey];
  }
  const labels = config.Labels || {};
  const version = labels["org.opencontainers.image.version"];
  if ((appVersionLabels.has(name) || name === "romm-db" || name === "mirklurk-db" || name === "mirklurk-backup")
      && validVersion(version) && !["latest", "main", "master"].includes(version)) {
    return version;
  }
  if (name === "hytale-server" && validVersion(version)) return `Wrapper ${version}`;
  const revision = labels["org.opencontainers.image.revision"];
  if (appRevisionSources[name] && appRevisionSources[name] === labels["org.opencontainers.image.source"]
      && /^[a-f0-9]{40}$/.test(revision || "")) {
    return `Build ${revision.slice(0, 12)}`;
  }
  if (!/^sha256:[a-f0-9]{64}$/.test(image.Id || "")) throw new InventoryError("Image identity missing");
  return `Image ${image.Id.slice(7, 19)}`;
}

function containerInfo(container, version, now) {
  const state = container.State;
  if (!state || typeof state.Running !== "boolean" || typeof state.Status !== "string") {
    throw new InventoryError("Invalid container state");
  }
  let uptime = "-";
  if (state.Running) {
    const started = Date.parse(state.StartedAt);
    if (!Number.isFinite(started) || started <= 0 || started > now) {
      throw new InventoryError("Invalid container start time");
    }
    const seconds = Math.floor((now - started) / 1000);
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor(seconds % 86400 / 3600);
    const minutes = Math.floor(seconds % 3600 / 60);
    uptime = days ? `${days}d ${hours}h` : hours ? `${hours}h ${minutes}m` : minutes ? `${minutes}m` : `${seconds}s`;
  }
  const items = [{ label: "App / Build", value: version }, { label: "Container Up", value: uptime }];
  const check = container.Config?.Healthcheck?.Test;
  const hasHealthcheck = Array.isArray(check) && check.length > 0 && check[0] !== "NONE";
  if (hasHealthcheck) {
    const health = state.Running ? state.Health?.Status : "Not running";
    if (!["healthy", "unhealthy", "starting", "Not running"].includes(health)) {
      throw new InventoryError("Invalid healthcheck state");
    }
    items.push({ label: "Health", value: health });
  }
  return { items };
}

function createServer({
  socketPath = "/var/run/docker.sock",
  project = "compose",
  requestDocker = (requestPath, options) => dockerRequest(socketPath, requestPath, options),
  now = Date.now,
  cacheMs = 10000,
  requestStats = readStats,
  logError = console.error,
} = {}) {
  const cache = new Map();
  const pending = new Map();
  async function inventory(name, withStats) {
    const key = `${withStats ? "stats" : "containers"}/${name}`;
    const cached = cache.get(key);
    if (cached && now() - cached.at < cacheMs) return cached.value;
    if (!pending.has(key)) {
      pending.set(key, (async () => {
        const container = await requestDocker(`/containers/${name}/json`);
        if (container.Config?.Labels?.["com.docker.compose.project"] !== project) {
          throw new InventoryError("Container is outside the dashboard project", 404);
        }
        if (!/^sha256:[a-f0-9]{64}$/.test(container.Image || "")) throw new InventoryError("Invalid image identity");
        const source = versionFiles[name];
        let version;
        if (source) {
          const archive = await requestDocker(
            `/containers/${name}/archive?path=${encodeURIComponent(source.path)}`, { binary: true },
          );
          let value;
          try {
            value = source.parse(archiveText(archive, path.posix.basename(source.path)));
          } catch (error) {
            if (error instanceof InventoryError) throw error;
            throw new InventoryError("Invalid application version file");
          }
          if (!validVersion(value)) throw new InventoryError("Application version missing from file");
          version = source.prefix + value;
        } else {
          const image = await requestDocker(`/images/${container.Image}/json`);
          version = imageVersion(name, image);
        }
        const value = containerInfo(container, version, now());
        if (withStats) {
          try {
            value.items.unshift(...await requestStats(name));
          } catch {
            throw new InventoryError(`Application statistics unavailable: ${name}`);
          }
        }
        if (cache.size >= 256) cache.clear();
        cache.set(key, { at: now(), value });
        return value;
      })().finally(() => pending.delete(key)));
    }
    return pending.get(key);
  }

  return http.createServer(async (request, response) => {
    const send = (status, value) => {
      response.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" });
      response.end(JSON.stringify(value));
    };
    const match = /^\/(containers|stats)\/([A-Za-z0-9][A-Za-z0-9_.-]{0,127})$/.exec(request.url);
    if (!match && request.url !== "/healthz") return send(404, { error: "Not found" });
    if (match?.[1] === "stats" && !Object.hasOwn(databaseFiles, match[2])) {
      return send(404, { error: "Not found" });
    }
    if (request.method !== "GET") {
      response.setHeader("Allow", "GET");
      return send(405, { error: "Method not allowed" });
    }
    try {
      if (request.url === "/healthz") {
        await requestDocker("/version");
        return send(200, { status: "ok" });
      }
      send(200, await inventory(match[2], match[1] === "stats"));
    } catch (error) {
      const message = error instanceof InventoryError ? error.message : "Unexpected inventory failure";
      logError(message);
      send(error instanceof InventoryError ? error.status : 500, { error: message });
    }
  });
}

if (require.main === module) {
  createServer().listen(8080, "0.0.0.0", () => console.log("Homepage inventory listening on port 8080"));
}

module.exports = { archiveText, containerInfo, createServer, dockerRequest, imageVersion, InventoryError };
