import { expect, test } from "@playwright/test";

test("the likeliest-failure search finds a rare collision and replays it", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "This is my first time" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.goto("/#/plan");
  await page.getByRole("tab", { name: "1 · Describe" }).click();
  await page
    .getByRole("region", { name: "Example workcells" })
    .getByRole("button", { name: /Flex to plate reader/ })
    .click();
  await expect(page.getByRole("button", { name: /^Step \d+ · / })).toHaveCount(
    1,
    { timeout: 60_000 },
  );

  // Drift wide enough that a collision exists, but only a few cycles in a thousand.
  await page.getByText("Perturbations and grip").click();
  await page.getByLabel("Instrument drift (mm)").fill("10");
  await page.getByLabel("Search budget").selectOption("100");
  const find = page.getByRole("button", { name: "Find the likeliest failure" });
  await expect(find).toBeEnabled();
  await find.click();

  const found = page.getByRole("list", { name: "Likeliest failures" });
  await expect(found).toContainText(
    /Collision · \d\.\dσ · about 1 in [\d,]+ cycles/,
    {
      timeout: 120_000,
    },
  );
  await expect(found).toContainText(/Plate reader .* drift x \+\d/);
  await expect(found).toContainText(/Found after \d+ of \d+ simulated cycles/);
  await expect(find).toBeEnabled({ timeout: 60_000 });

  await found.getByRole("button", { name: "Replay" }).first().click();
  await expect(page.getByText(/Found cycle · 1 failed/)).toBeVisible();
  await expect(page.getByText(/Stress cycle · Step 3/)).toBeVisible();
  await expect(
    page.getByText(/Step 3: the gripper hits Plate reader/).last(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Back to the planned path" }).click();
  await expect(page.getByText(/Planned path · Step 3/)).toBeVisible();

  // At the default spread nothing fails within 3σ; the closest approach is shown.
  await page.getByLabel("Instrument drift (mm)").fill("2");
  await find.click();
  await expect(found).toContainText(/No failure within ±3σ in \d+ cycles/, {
    timeout: 120_000,
  });
  await expect(found).toContainText(/Closest collision · \d+% margin left at/);
  await page.screenshot({ path: "/tmp/academy-adversary.png", fullPage: true });
  expect(errors).toEqual([]);
});
