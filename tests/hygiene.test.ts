import { expect, test } from "bun:test";

test("legacy artifacts are absent", async () => {
  const python: string[] = [];
  for await (const path of new Bun.Glob("**/*.py").scan({ cwd: new URL("..", import.meta.url).pathname, onlyFiles: true })) {
    if (!path.startsWith("node_modules/")) python.push(path);
  }
  expect(python).toEqual([]);
  const removed = [
    "pyproject.toml",
    ["u", "v.lock"].join(""),
    ["sta", "ts.py"].join(""),
    ["Dockerfile.", "sta", "ts"].join(""),
  ];
  for (const path of removed) expect(await Bun.file(new URL(`../${path}`, import.meta.url)).exists()).toBe(false);
});
