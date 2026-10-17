// An R2 binding backed by a folder, for tests: get(key) -> {size, body, json()} or null.
import { readFileSync, statSync } from "node:fs";
import { join } from "node:path";

export function folderBucket(root) {
  return {
    async get(key) {
      const path = join(root, ...key.split("/"));
      let size;
      try {
        size = statSync(path).size;
      } catch {
        return null;
      }
      const data = readFileSync(path);
      return {
        size,
        body: new Blob([data]).stream(),
        json: async () => JSON.parse(data.toString("utf8")),
      };
    },
  };
}
