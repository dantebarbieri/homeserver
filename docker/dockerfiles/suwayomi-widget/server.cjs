const http = require("node:http");
const { timingSafeEqual } = require("node:crypto");

const fields = {
  download: "isDownloaded: true",
  nondownload: "isDownloaded: false",
  read: "isRead: true",
  unread: "isRead: false",
};
const countsQuery = `query Counts {
  ${Object.entries(fields).map(([name, condition]) => `
    ${name}: chapters(condition: {${condition}}, filter: {inLibrary: {equalTo: true}}) {
      totalCount
    }`).join("\n")}
}`;

class UpstreamError extends Error {
  constructor(message, { unauthorized = false, status = 502 } = {}) {
    super(message);
    this.unauthorized = unauthorized;
    this.status = status;
  }
}

function createServer({
  url,
  username,
  password,
  fetchImpl = fetch,
  timeoutMs = 10000,
  logError = console.error,
}) {
  if (!url || !username || !password) {
    throw new Error("SUWAYOMI_URL, SUWAYOMI_USERNAME and SUWAYOMI_PASSWORD are required");
  }
  const endpoint = new URL("api/graphql", `${url.replace(/\/+$/, "")}/`);
  const authorization = Buffer.from(`Basic ${Buffer.from(`${username}:${password}`).toString("base64")}`);
  let token;
  let loginPending;

  async function graphql(query, variables, accessToken) {
    let response;
    let result;
    try {
      response = await fetchImpl(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
        body: JSON.stringify({ query, variables }),
        redirect: "error",
        signal: AbortSignal.timeout(timeoutMs),
      });
      if (response.status === 401) {
        throw new UpstreamError("Suwayomi authentication failed", { unauthorized: true });
      }
      if (!response.ok) {
        throw new UpstreamError(`Suwayomi returned HTTP ${response.status}`);
      }
      result = await response.json();
    } catch (error) {
      if (error instanceof UpstreamError) throw error;
      if (error.name === "TimeoutError" || error.name === "AbortError") {
        throw new UpstreamError("Suwayomi request timed out", { status: 504 });
      }
      // Never expose upstream bodies, stack traces, credentials or tokens.
      throw new UpstreamError("Suwayomi request failed or returned invalid JSON");
    }
    if (Array.isArray(result?.errors) && result.errors.length) {
      const unauthorized = result.errors.some((error) => /\bUnauthorized\b/i.test(error.message));
      throw new UpstreamError(
        unauthorized ? "Suwayomi authentication failed" : "Suwayomi returned GraphQL errors",
        { unauthorized },
      );
    }
    if (!result?.data || typeof result.data !== "object") {
      throw new UpstreamError("Suwayomi returned no GraphQL data");
    }
    return result.data;
  }

  async function getToken(rejectedToken) {
    if (rejectedToken && token === rejectedToken) token = undefined;
    if (token) return token;
    if (!loginPending) {
      loginPending = (async () => {
        const data = await graphql(
          "mutation Login($input: LoginInput!) { login(input: $input) { accessToken } }",
          { input: { username, password } },
        );
        if (typeof data.login?.accessToken !== "string" || !data.login.accessToken) {
          throw new UpstreamError("Suwayomi login returned no access token");
        }
        token = data.login.accessToken;
        return token;
      })().finally(() => { loginPending = undefined; });
    }
    return loginPending;
  }

  async function getCounts() {
    const accessToken = await getToken();
    let data;
    try {
      data = await graphql(countsQuery, undefined, accessToken);
    } catch (error) {
      if (!error.unauthorized) throw error;
      data = await graphql(countsQuery, undefined, await getToken(accessToken));
    }
    const counts = {};
    for (const name of Object.keys(fields)) {
      const value = data[name]?.totalCount;
      if (!Number.isSafeInteger(value) || value < 0) {
        throw new UpstreamError(`Suwayomi returned an invalid ${name} count`);
      }
      counts[name] = value;
    }
    return counts;
  }

  return http.createServer(async (request, response) => {
    const send = (status, body) => {
      response.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" });
      response.end(JSON.stringify(body));
    };
    if (request.url !== "/stats") return send(404, { error: "Not found" });
    if (request.method !== "GET") {
      response.setHeader("Allow", "GET");
      return send(405, { error: "Method not allowed" });
    }
    const supplied = Buffer.from(request.headers.authorization || "");
    if (supplied.length !== authorization.length || !timingSafeEqual(supplied, authorization)) {
      response.setHeader("WWW-Authenticate", 'Basic realm="Suwayomi widget"');
      return send(401, { error: "Authentication required" });
    }
    try {
      send(200, await getCounts());
    } catch (error) {
      const message = error instanceof UpstreamError ? error.message : "Unexpected widget adapter failure";
      logError(message);
      send(error instanceof UpstreamError ? error.status : 500, { error: message });
    }
  });
}

if (require.main === module) {
  const server = createServer({
    url: process.env.SUWAYOMI_URL,
    username: process.env.SUWAYOMI_USERNAME,
    password: process.env.SUWAYOMI_PASSWORD,
  });
  server.listen(8080, "0.0.0.0", () => console.log("Suwayomi widget listening on port 8080"));
}

module.exports = { createServer };
