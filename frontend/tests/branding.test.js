import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("installable app icons match the sizes declared in the manifest", () => {
  const assets = new URL("../public/", import.meta.url);
  const manifest = JSON.parse(readFileSync(new URL("manifest.webmanifest", assets), "utf8"));
  for (const size of [192, 512]) {
    const icon = manifest.icons.find(item => item.type === "image/png" && item.sizes === `${size}x${size}`);
    assert.ok(icon, `Missing ${size}px install icon`);
    const png = readFileSync(new URL(icon.src.replace(/^\//, ""), assets));
    assert.equal(png.readUInt32BE(16), size);
    assert.equal(png.readUInt32BE(20), size);
  }
});
