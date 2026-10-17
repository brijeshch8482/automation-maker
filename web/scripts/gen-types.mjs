// Generate src/types/spec.gen.ts from spec/schema/automation_spec.schema.json.
//   node scripts/gen-types.mjs           write the file
//   node scripts/gen-types.mjs --check   fail if the committed file is stale
import { readFile, writeFile } from "node:fs/promises";
import { compile } from "json-schema-to-typescript";

const schemaUrl = new URL("../../spec/schema/automation_spec.schema.json", import.meta.url);
const outUrl = new URL("../src/types/spec.gen.ts", import.meta.url);

const schema = JSON.parse(await readFile(schemaUrl, "utf8"));

// Pydantic titles every property, which makes json-schema-to-typescript emit an alias per
// property (Key1, Label7, ...). Keep titles only on the models in $defs.
function dropPropertyTitles(node) {
  if (Array.isArray(node)) return node.forEach(dropPropertyTitles);
  if (!node || typeof node !== "object") return;
  for (const prop of Object.values(node.properties ?? {})) delete prop.title;
  Object.values(node).forEach(dropPropertyTitles);
}
dropPropertyTitles(schema);
const ts = await compile(schema, "AutomationSpec", {
  bannerComment:
    "/* Generated from spec/schema/automation_spec.schema.json by `npm run gen:types`. Do not edit. */",
  additionalProperties: false,
  style: { singleQuote: false, printWidth: 100 },
});

if (process.argv.includes("--check")) {
  const current = await readFile(outUrl, "utf8").catch(() => "");
  if (current !== ts) {
    console.error("src/types/spec.gen.ts is stale: run `npm run gen:types`");
    process.exit(1);
  }
} else {
  await writeFile(outUrl, ts);
  console.log("wrote src/types/spec.gen.ts");
}
