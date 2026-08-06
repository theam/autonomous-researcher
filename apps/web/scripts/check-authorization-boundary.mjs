import { readdir, readFile } from "node:fs/promises";
import { extname, join, relative } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const targets = [join(root, "app"), join(root, "components"), join(root, "lib")];
const forbidden = /(?:\brole|\.role)\s*(?:===|!==|==|!=)/;
const failures = [];

async function scan(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      await scan(path);
      continue;
    }
    if (![".ts", ".tsx"].includes(extname(entry.name)) || entry.name.endsWith(".test.ts")) {
      continue;
    }
    const lines = (await readFile(path, "utf8")).split("\n");
    lines.forEach((line, index) => {
      if (forbidden.test(line)) failures.push(`${relative(root, path)}:${index + 1}`);
    });
  }
}

for (const target of targets) await scan(target);

if (failures.length) {
  throw new Error(
    `Project authorization must use server-derived capabilities, not role comparisons:\n${failures.join("\n")}`,
  );
}
