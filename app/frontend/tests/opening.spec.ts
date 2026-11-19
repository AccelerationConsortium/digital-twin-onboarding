import { expect, test } from "@playwright/test";

test("a Flex entered through half of a side window gets layouts through that half", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "This is my first time" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.goto("/#/plan");
  await page.getByRole("tab", { name: "1 · Describe" }).click();
  // The example without a saved layout, so the Flex can be changed freely.
  await page
    .getByRole("region", { name: "Example workcells" })
    .getByRole("button", { name: /No layout yet/ })
    .click();
  await page.getByRole("tab", { name: "2 · Instruments" }).click();

  const flex = page
    .locator("article")
    .filter({ hasText: "Liquid handler (Opentrons Flex)" })
    .first();
  await flex.getByLabel("Loaded").selectOption("left");
  await flex.getByLabel("Open part").selectOption("second");
  await expect(
    flex.getByLabel("Open part").locator("option:checked"),
  ).toHaveText("Front half");
  const saved = page.waitForResponse(
    (r) => r.url().includes("/confirm") && r.request().method() === "PUT",
  );
  await flex.getByRole("button", { name: "Save revision" }).click();
  expect((await saved).status()).toBe(200);

  // The open half is marked on the bench.
  await page.getByRole("tab", { name: "4 · Layout" }).click();
  const line = page.locator("svg line[class*='opening']");
  await expect(line).toHaveCount(1);
  // The saved opening is the front half of the left side, and the bench draws half
  // the Flex's depth, not the whole side.
  const twins = await (await page.request.get("/api/twins")).json();
  const twin = twins.twins.find((t: { spec?: { opening?: unknown } }) =>
    Boolean(t.spec?.opening),
  );
  expect(twin.spec.opening).toEqual({ face: "left", start: 0.5, end: 1 });
  const parts = twin.spec.parts as { size: number[]; position: number[] }[];
  const depth =
    Math.max(...parts.map((p) => p.position[2] + p.size[2] / 2)) -
    Math.min(...parts.map((p) => p.position[2] - p.size[2] / 2));
  const [x1, y1, x2, y2] = await Promise.all(
    ["x1", "y1", "x2", "y2"].map(async (k) =>
      Number(await line.getAttribute(k)),
    ),
  );
  expect(Math.hypot(x2 - x1, y2 - y1)).toBeCloseTo(depth / 2, 2);
});
