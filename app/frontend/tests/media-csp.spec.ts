import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

// Exercise the actual Terraform header in Chromium, rather than the fake
// WebSocket implementation used by native UI contract fixtures.
test("CSP permits Canadian KVS signaling while blocking other regions and hosts", async ({
  page,
}) => {
  const source = readFileSync(path.resolve("../../platform/main.tf"), "utf8");
  const template = source.match(/content_security_policy = "([^"]+)"/);
  expect(template).not.toBeNull();
  const policy = template![1]
    .replaceAll("${var.region}", "ca-central-1")
    .replace(
      "${aws_cognito_user_pool.learners.endpoint}",
      "cognito-idp.ca-central-1.amazonaws.com/example",
    )
    .replace(
      "${aws_cognito_user_pool_domain.learners.domain}",
      "academy-example",
    );
  await page.route("**/csp-check", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/html",
      headers: { "Content-Security-Policy": policy },
      body: "<!doctype html><title>Native signaling policy check</title>",
    }),
  );
  await page.goto("/csp-check");
  const blocked = await page.evaluate(async () => {
    const violations: string[] = [];
    const listener = (event: SecurityPolicyViolationEvent) => {
      if (event.effectiveDirective === "connect-src")
        violations.push(event.blockedURI);
    };
    document.addEventListener("securitypolicyviolation", listener);
    const sockets = [
      "wss://v-csp-check.kinesisvideo.ca-central-1.amazonaws.com/",
      "wss://v-csp-check.kinesisvideo.us-east-1.amazonaws.com/",
      "wss://untrusted.invalid/",
    ].map((url) => new WebSocket(url));
    await new Promise((resolve) => setTimeout(resolve, 500));
    for (const socket of sockets) socket.close();
    document.removeEventListener("securitypolicyviolation", listener);
    return violations;
  });
  expect(
    blocked.some((url) => url.includes("ca-central-1.amazonaws.com")),
  ).toBe(false);
  expect(blocked.some((url) => url.includes("us-east-1.amazonaws.com"))).toBe(
    true,
  );
  expect(blocked.some((url) => url.includes("untrusted.invalid"))).toBe(true);
});

test("CSP lets 3D models load their embedded textures but no other hosts", async ({
  page,
}) => {
  const source = readFileSync(path.resolve("../../platform/main.tf"), "utf8");
  const policy = source
    .match(/content_security_policy = "([^"]+)"/)![1]
    .replaceAll("${var.region}", "ca-central-1")
    .replace(
      "${aws_cognito_user_pool.learners.endpoint}",
      "cognito-idp.ca-central-1.amazonaws.com/example",
    )
    .replace(
      "${aws_cognito_user_pool_domain.learners.domain}",
      "academy-example",
    );
  await page.route("**/csp-textures", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/html",
      headers: { "Content-Security-Policy": policy },
      body: "<!doctype html><title>Model texture policy check</title>",
    }),
  );
  await page.goto("/csp-textures");
  const result = await page.evaluate(async () => {
    // GLTFLoader turns a GLB's embedded images into blob: URLs and fetches them.
    const png = Uint8Array.from(
      atob(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==",
      ),
      (c) => c.charCodeAt(0),
    );
    const url = URL.createObjectURL(new Blob([png], { type: "image/png" }));
    const fetched = await fetch(url).then(
      (r) => r.ok,
      () => false,
    );
    const image = await new Promise<boolean>((resolve) => {
      const img = new Image();
      img.onload = () => resolve(true);
      img.onerror = () => resolve(false);
      img.src = url;
    });
    const outside = await fetch("https://untrusted.invalid/model.glb").then(
      () => true,
      () => false,
    );
    return { fetched, image, outside };
  });
  expect(result).toEqual({ fetched: true, image: true, outside: false });
});
