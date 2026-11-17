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
  // An example without a saved layout, so the Flex can be changed freely.
  await page
    .getByRole("region", { name: "Example workcells" })
    .getByRole("button", { name: /Flex, incubated shaker, plate reader/ })
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
  await expect(page.locator("svg line[class*='opening']")).toHaveCount(1);
});
