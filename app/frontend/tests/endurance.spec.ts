import { expect, test } from "@playwright/test";

test("a stress run repeats the transfers and replays the worst cycle", async ({
  page,
}) => {
  test.setTimeout(150_000);
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
  const paths = page.getByRole("button", { name: /^Step \d+ · / });
  await expect(paths).toHaveCount(1, { timeout: 60_000 });

  const run = page.getByRole("button", { name: "Run endurance test" });
  await expect(run).toBeEnabled();
  await page.getByLabel("Cycles").selectOption("50");
  await run.click();

  // The planned path's grasp comes first, then every cycle is counted.
  const grasp = page.getByRole("list", { name: "Grasp on the planned path" });
  await expect(grasp).toContainText(/Step 3 grasp · \d+\.\d× margin/, {
    timeout: 60_000,
  });
  await expect(grasp).toContainText("of 16.0 N friction · least during");
  await expect(page.getByText("0 of 50", { exact: true })).toBeVisible({
    timeout: 90_000,
  });
  await expect(page.getByText(/cm min · .* cm median/)).toBeVisible();
  await expect(page.getByText(/s median · .* s p95/)).toBeVisible();
  await expect(page.getByText(/Defaults used: grip 20 N/)).toBeVisible();

  // With nothing failing, the tightest cycle is the one to look at again.
  await expect(
    page.getByText(/Tightest cycle · cycle \d+, seed 1/),
  ).toBeVisible();
  await page.getByRole("button", { name: "Replay" }).click();
  await expect(page.getByText(/Endurance cycle · Step 3/)).toBeVisible();
  await expect(
    page.getByText(/Picked .* mm off, placed .* mm off/),
  ).toBeVisible();
  await page.getByRole("button", { name: "Back to the planned path" }).click();
  await expect(page.getByText(/Planned path · Step 3/)).toBeVisible();

  // A plate too heavy for the grip drops in every cycle, and the first one is named.
  await page.getByText("Perturbations and grip").click();
  await page.getByLabel("Labware mass (kg)").fill("3");
  await run.click();
  await expect(page.getByText("50 of 50 (100.0%)")).toBeVisible({
    timeout: 90_000,
  });
  await expect(page.getByText("Drop 50")).toBeVisible();
  await expect(page.getByText(/First failure · cycle 0, seed 1/)).toBeVisible();
  await expect(
    page
      .getByText(/the plate slides out of the gripper during lift from/)
      .first(),
  ).toBeVisible();
  await page.screenshot({
    path: "/tmp/academy-endurance.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
