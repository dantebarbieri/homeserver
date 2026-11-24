export const TYPES = {
  endlessh: {label: "Endlessh", color: "#aab8ca"},
  ssh: {label: "Real SSH", color: "#f4f7ff"},
  authelia: {label: "Authelia", color: "#f397ad"},
  web: {label: "Web / NPM", color: "#71d5ed"},
  minecraft: {label: "Minecraft", color: "#94dfa5"},
  plex: {label: "Plex", color: "#efc477"},
  game: {label: "Other games", color: "#bc9ceb"},
  git: {label: "Git SSH", color: "#82a8ff"},
};

export const MAP_DEFAULTS = {keep: 7, fadeMinutes: 30, maxDots: 300};

export function mapSettings(input) {
  const result = {};
  for (const [key, min, max] of [["keep", 0, 1000], ["fadeMinutes", 1, 1440], ["maxDots", 1, 1000]]) {
    const value = Number(input?.[key]);
    if (input?.[key] === "" || input?.[key] == null || !Number.isInteger(value) || value < min || value > max)
      throw new Error(`Map setting ${key} must be a whole number between ${min} and ${max}.`);
    result[key] = value;
  }
  if (result.keep > result.maxDots) throw new Error("Keep newest cannot exceed the maximum map dots.");
  return result;
}

export function mapActivity(events, settings, now = Date.now() / 1000, history = false) {
  const ordered = events.filter(item => located(item) && Number.isFinite(item.observedAt))
    .toSorted((a, b) => b.observedAt - a.observedAt || a.id.localeCompare(b.id));
  const visible = [];
  let expired = 0;
  for (const [index, item] of ordered.entries()) {
    // The dot starts aging when displaced from the held group, not on page load.
    const start = ordered[Math.max(0, index - settings.keep)].observedAt;
    const opacity = index < settings.keep ? 1 : Math.max(0, Math.min(1, 1 - (now - start) / (settings.fadeMinutes * 60)));
    if (opacity === 0) expired++;
    if (opacity > 0 || history) visible.push({item, opacity: opacity || .12});
  }
  return {points: visible.slice(0, settings.maxDots), expired, omitted: Math.max(0, visible.length - settings.maxDots)};
}

export function countryFlag(code) {
  if (typeof code !== "string" || !/^[A-Z]{2}$/.test(code) || ["ZZ", "XX"].includes(code)) return "";
  return [...code].map(letter => String.fromCodePoint(0x1f1e6 + letter.charCodeAt(0) - 65)).join("");
}

export function mergeEvents(current, incoming, limit = 1000) {
  const all = new Map(current.map(item => [item.id, item]));
  for (const item of incoming) if (TYPES[item.type]) all.set(item.id, item);
  return [...all.values()].sort((a, b) => BigInt(a.cursor) > BigInt(b.cursor) ? -1 : BigInt(a.cursor) < BigInt(b.cursor) ? 1 : a.id.localeCompare(b.id)).slice(0, limit);
}

export function equalEarth(longitude, latitude) {
  const radians = Math.PI / 180;
  const theta = Math.asin(Math.sqrt(3) / 2 * Math.sin(latitude * radians));
  // Equal Earth (Savric, Patterson & Jenny, 2018), spherical forward equations.
  const coefficients = [[1, 1.340264], [3, -.081106], [7, .000893], [9, .003796]];
  const vertical = coefficients.reduce((sum, [power, value]) => sum + value * theta ** power, 0);
  const derivative = coefficients.reduce((sum, [power, value]) => sum + power * value * theta ** (power - 1), 0);
  return [2 * longitude * radians * Math.cos(theta) / (Math.sqrt(3) * derivative), vertical];
}

export function project(longitude, latitude, width, height, projection = "equal-earth") {
  if (projection === "rectangular") {
    const scale = Math.min(width / 380, height / 190);
    return [width / 2 + longitude * scale, height / 2 - latitude * scale];
  }
  const [x, y] = equalEarth(longitude, latitude);
  const scale = Math.min(width / (equalEarth(180, 0)[0] * 2.12), height / (equalEarth(0, 90)[1] * 2.12));
  return [width / 2 + x * scale, height / 2 - y * scale];
}

export function located(event) {
  return Number.isFinite(event.latitude) && Number.isFinite(event.longitude)
    && Math.abs(event.latitude) <= 90 && Math.abs(event.longitude) <= 180;
}

export function duration(seconds) {
  if (!Number.isFinite(seconds)) return "—";
  if (seconds >= 86400) return `${(seconds / 86400).toFixed(1)} d`;
  if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)} h`;
  if (seconds >= 60) return `${Math.round(seconds / 60)} min`;
  return `${Math.round(seconds)} s`;
}

export function demoEvents(now = Date.now()) {
  const places = [[-74, 40.7, "New York, United States", "US"], [13.4, 52.5, "Berlin, Germany", "DE"],
    [103.8, 1.3, "Singapore", "SG"], [-46.6, -23.6, "São Paulo, Brazil", "BR"],
    [139.7, 35.7, "Tokyo, Japan", "JP"], [2.4, 48.9, "Paris, France", "FR"],
    [151.2, -33.9, "Sydney, Australia", "AU"], [77.2, 28.6, "New Delhi, India", "IN"]];
  const providers = ["AWS", "Azure", "Google Cloud", "Oracle Cloud", "Vercel", "Hetzner", "Cloudflare", "Example ISP"];
  const kinds = ["tarpit_open", "ssh_probe", "auth_failure", "http_probe", "service_connection", "service_connection", "service_connection", "service_connection"];
  return Array.from({length: 32}, (_, i) => {
    const type = Object.keys(TYPES)[i % 8], place = places[(i * 3) % 8];
    const timestamp = (now - i * 17000) / 1000;
    const item = {id: `demo-${i}`, cursor: String(BigInt(Math.floor(timestamp * 1000)) * 1000000n),
      timestamp, observedAt: timestamp, type, kind: kinds[i % 8],
      title: ["Entered tarpit", "Targeted real SSH port", "Authelia sign-in failed", "Suspicious web request", "Service connection"][Math.min(i % 8, 4)],
      verdict: type === "authelia" ? "failure" : type === "web" ? "suspected" : type === "endlessh" ? "observed" : "unclassified",
      ip: `192.0.2.${i + 1}`, port: [22, 28, 443, 443, 36676, 32400, 5205, 2222][i % 8],
      service: TYPES[type].label, source: "synthetic", user: type === "authelia" ? "example-user" : undefined,
      path: type === "web" ? "/.env" : undefined,
      longitude: place[0], latitude: place[1], location: place[2], countryCode: place[3],
      networkLookup: "ready", networkProvider: providers[i % 8], asn: 64512 + i % 8,
      networkOrganization: "Synthetic example network (private-use ASN)", networkEvidence: "Synthetic preview association, not a real IP lookup",
      privacyServices: i % 8 > 0 && i % 8 < 4 ? [{
        name: ["", "Mullvad", "NordVPN", "Tor"][i % 8], kind: i % 8 === 3 ? "tor_exit" : "vpn_server",
        evidence: "Synthetic association for preview only; not a real VPN or Tor lookup", updatedAt: now / 1000,
      }] : []};
    if (type === "ssh") {
      const variant = Math.floor(i / 8);
      item.user = variant === 0 ? "root123" : "example-user";
      if (variant === 0) Object.assign(item, {kind: "ssh_failure", title: "SSH authentication failed", verdict: "failure", authMethod: "unknown", rejectionReason: "Username does not exist"});
      else if (variant < 3) Object.assign(item, {kind: variant === 1 ? "ssh_accepted" : "ssh_accepted_unknown",
        title: variant === 1 ? "SSH login accepted" : "SSH accepted: unregistered credential", verdict: "accepted",
        authMethod: "publickey", keyStatus: variant === 1 ? "recognized" : "unregistered",
        keyLabel: variant === 1 ? "Example desktop (synthetic)" : undefined, keyFingerprint: "SHA256:synthetic-demo-fingerprint"});
      else Object.assign(item, {kind: "ssh_disconnect", title: "SSH disconnected before login", verdict: "incomplete", authMethod: "unknown"});
    }
    return item;
  });
}
