import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const lockfile = JSON.parse(
  readFileSync(new URL("../package-lock.json", import.meta.url), "utf8"),
);

for (const [provider, prefix] of [["next", "@next/swc-"], ["sharp", "@img/"]]) {
  test(`${provider} locks every declared platform-specific optional package`, () => {
    const parent = lockfile.packages[`node_modules/${provider}`];
    assert.ok(parent, `${provider} must be present in the lockfile`);
    const declared = Object.keys(parent.optionalDependencies ?? {}).filter(
      (name) => name.startsWith(prefix),
    );
    assert.ok(declared.length > 0, `${provider} must declare platform packages`);
    const required = new Set(declared);
    // Platform adapters may share WASM and emnapi runtime packages.
    for (const name of required) {
      const entry = lockfile.packages[`node_modules/${name}`];
      for (const dependency of Object.keys(entry?.dependencies ?? {})) {
        if (dependency.startsWith(prefix) || dependency === "@emnapi/runtime") {
          required.add(dependency);
        }
      }
    }
    const missing = [...required].filter(
      (name) => !lockfile.packages[`node_modules/${name}`],
    );
    assert.deepEqual(missing, [], `Missing ${provider} lock records: ${missing.join(", ")}`);
    for (const name of required) {
      const entry = lockfile.packages[`node_modules/${name}`];
      assert.equal(entry.optional, true, `${name} must remain optional`);
      assert.notEqual(entry.dev, true, `${name} must not be development-only`);
      assert.notEqual(entry.peer, true, `${name} must not be peer-only`);
      assert.ok(entry.version && entry.resolved && entry.integrity, `${name} must have locked version and integrity metadata`);
    }
  });
}
