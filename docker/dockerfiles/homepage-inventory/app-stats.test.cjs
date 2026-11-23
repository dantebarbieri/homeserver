const assert = require("node:assert/strict");
const { test } = require("node:test");
const { applicationStats, metricValues, pdfCatalog, statsNames, toolCatalog, toolCatalogAsset } = require("./app-stats.cjs");

test("compiled ConvertX releases need only SQLite aggregates, not archived JavaScript files", async () => {
  const result = { completed: "31", other: "4", jobs: "0" };
  assert.deepEqual(await applicationStats("convertx", {
    readSqliteStats: (name) => {
      assert.equal(name, "convertx");
      return result;
    },
  }), result);
  await assert.rejects(applicationStats("convertx", {
    readSqliteStats: () => { throw new Error("Database unavailable"); },
  }), /Database unavailable/);
});

test("tool catalog counts registered tools and their categories, without executing scripts", () => {
  const bundle = `
    one=define({name:translate("tools.one.title"),path:\`/one\`,description:translate("one"),icon:load(()=>x),category:\`Crypto\`});
    two=define({name:"Two",path:\`/two\`,redirectFrom:[\`/old-two\`],description:"Two",component:()=>import(\`./two.js\`),category:\`Web\`});
    three=define({name:"Three",path:\`/three\`,description:"Three"});
    throw new Error("must not execute");
  `;
  assert.deepEqual(toolCatalog(bundle), { tools: "3", categories: "3" });
  assert.deepEqual(toolCatalog(bundle.replace("category:`Web`", "category:`Crypto`")), { tools: "3", categories: "2" });
  assert.throws(() => toolCatalog(bundle.replace("/three", "/one")), /Duplicate/);
  assert.throws(() => toolCatalog("<html>login</html>"), /Unrecognized/);
});

test("tool catalog chunk is found from the modulepreload link, with the base-relative path", () => {
  assert.equal(toolCatalogAsset('<link rel="modulepreload" crossorigin href="./assets/tools.store-CTlhXkV0.js">'),
    "assets/tools.store-CTlhXkV0.js");
  assert.equal(toolCatalogAsset('<link href="/assets/tools.store-a_b-1.js" rel="modulepreload">'), "assets/tools.store-a_b-1.js");
  assert.equal(toolCatalogAsset('<script src="./assets/index-abc.js"></script>'), undefined);
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

test("metrics require a real declared family and valid samples, including an explicitly empty family", () => {
  assert.deepEqual(metricValues('# TYPE calls counter\ncalls{engine="a"} 12\ncalls{engine="b"} 4\n', "calls"), [12, 4]);
  assert.deepEqual(metricValues("# TYPE calls counter\n", "calls"), []);
  assert.throws(() => metricValues("<html>authentication</html>", "calls"), /Missing metric/);
  for (const value of ["NaN", "-1", "+Inf"]) {
    assert.throws(() => metricValues(`# TYPE calls counter\ncalls ${value}\n`, "calls"), /Invalid metric/);
  }
});

test("statistics source allowlist cannot expose arbitrary service, URL, or file requests", () => {
  for (const name of ["convertx", "snapotter", "authelia", "synapse", "element", "it-tools", "stirling-pdf", "searxng"]) {
    assert.ok(statsNames.has(name));
  }
  for (const name of ["toString", "http://example.com", "../../etc/shadow", "unknown"]) {
    assert.ok(!statsNames.has(name));
  }
});
