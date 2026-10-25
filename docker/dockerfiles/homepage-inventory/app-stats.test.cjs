const assert = require("node:assert/strict");
const { test } = require("node:test");
const { metricValues, pdfCatalog, peerStats, statsNames, toolCatalog } = require("./app-stats.cjs");

test("tool catalog counts only registered category members, without executing scripts", () => {
  const bundle = `
    one=define({name:translate("tools.one.title"),path:"/one",description:translate("one")});
    two=define({name:"Two",path:"/two",description:"Two"});
    groups=[{name:"Crypto",components:[one]},{name:"Web",components:[two]}];
    throw new Error("must not execute");
  `;
  assert.deepEqual(toolCatalog(bundle), { tools: "2", categories: "2" });
  assert.throws(() => toolCatalog(bundle.replace("components:[two]", "components:[missing]")), /Incomplete/);
  assert.throws(() => toolCatalog(bundle.replace("components:[two]", "components:[one]")), /Incomplete/);
  assert.throws(() => toolCatalog("<html>login</html>"), /Unrecognized/);
});

test("PDF actions exclude administration and count file-accepting document APIs, not every POST", () => {
  const upload = { content: { "multipart/form-data": { schema: { $ref: "#/components/schemas/Upload" } } } };
  const document = {
    openapi: "3.0.1",
    components: { schemas: { Upload: { properties: { files: { type: "array", items: { type: "string", format: "binary" } } } } } },
    paths: {
      "/api/v1/convert": { post: { tags: ["Convert"], requestBody: upload } },
      "/api/v1/compress": { post: { tags: ["General"], requestBody: upload } },
      "/api/v1/admin/import": { post: { tags: ["Admin Settings"], requestBody: upload } },
      "/api/v1/general-settings": { post: { tags: ["General"], requestBody: { content: { "application/json": {} } } } },
    },
  };
  assert.deepEqual(pdfCatalog(document), { actions: "2", categories: "2" });
  assert.throws(() => pdfCatalog({ paths: {} }), /Missing API/);
  assert.throws(() => pdfCatalog({ openapi: "3.0", paths: {} }), /Missing PDF/);
});

test("peer aggregates expose no names, keys or addresses, and never claim an enabled peer is connected", () => {
  const value = { server: { privateKey: "private" }, clients: {
    one: { enabled: true, name: "private", publicKey: "private" },
    two: { enabled: false, address: "private" },
  } };
  assert.deepEqual(peerStats(JSON.stringify(value)), { peers: "2", enabled: "1" });
  assert.deepEqual(peerStats('{"clients":{}}'), { peers: "0", enabled: "0" });
  assert.throws(() => peerStats('{"clients":{"one":{"enabled":"true"}}}'), /Invalid peer/);
  assert.throws(() => peerStats('{"clients":[]}'), /Invalid peer configuration/);
});

test("metrics require a real declared family and valid samples, including an explicitly empty family", () => {
  assert.deepEqual(metricValues('# TYPE calls counter\ncalls{engine="a"} 12\ncalls{engine="b"} 4\n', "calls"), [12, 4]);
  assert.deepEqual(metricValues("# TYPE calls counter\n", "calls"), []);
  assert.throws(() => metricValues("<html>authentication</html>", "calls"), /Missing metric/);
  for (const value of ["NaN", "-1", "+Inf"]) {
    assert.throws(() => metricValues(`# TYPE calls counter\ncalls ${value}\n`, "calls"), /Invalid metric/);
  }
});

test("statistics source allowlist cannot expose arbitrary service, URL, or file requests", () => {
  for (const name of ["convertx", "snapotter", "authelia", "synapse", "element", "it-tools", "stirling-pdf", "wg-easy", "searxng"]) {
    assert.ok(statsNames.has(name));
  }
  for (const name of ["toString", "http://example.com", "../../etc/shadow", "unknown"]) {
    assert.ok(!statsNames.has(name));
  }
});
