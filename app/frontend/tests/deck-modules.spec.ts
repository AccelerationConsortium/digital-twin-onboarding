import { expect, test } from "@playwright/test";

test("a learner adds deck modules and the twin stops a module mistake", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "This is my first time" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.goto("/#/instruments");
  await page.getByRole("button", { name: /Use this workflow/ }).click();
  const studio = page.getByTestId("workflow-studio");
  await expect(studio).toBeVisible({ timeout: 30_000 });

  // Module steps appear once a module is on the deck.
  const palette = page.getByRole("group", { name: "Add a workflow block" });
  await expect(
    palette.getByRole("button", { name: "Add move plate block" }),
  ).toHaveCount(0);
  const modules = page.getByRole("group", { name: "Deck modules" });
  await modules.getByRole("button", { name: /Gripper/ }).click();
  await modules.getByRole("button", { name: /Heater-Shaker/ }).click();
  await modules.getByRole("button", { name: /Plate reader/ }).click();
  await expect(
    page.getByRole("button", { name: "Slot C1: Heater-Shaker" }),
  ).toBeVisible();

  // Heat before the plate is on the module: the mistake a newcomer makes.
  const steps = await page.getByTestId(/^workflow-step-\d+$/).count();
  await palette
    .getByRole("button", { name: "Add set temperature block" })
    .click();
  await page.getByLabel(`Step ${steps + 1} temperature`).fill("60");
  await palette.getByRole("button", { name: "Add move plate block" }).click();
  await expect(page.getByLabel(`Step ${steps + 2} destination`)).toHaveValue(
    "heater_shaker",
  );
  await page.getByRole("button", { name: /Save/ }).first().click();
  await page.getByRole("button", { name: "Run teaching simulation" }).click();
  await expect(
    page.getByText("which cannot set a temperature", { exact: false }).first(),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByLabel("Sample plate")).toContainText("Deck");

  // Put the move first and the run completes with the plate on the module.
  await page.getByRole("button", { name: "Reset & edit" }).click();
  await page.getByRole("button", { name: `Move step ${steps + 2} up` }).click();
  await page.getByRole("button", { name: /Save/ }).first().click();
  await page.getByRole("button", { name: "Run teaching simulation" }).click();
  await expect(page.getByLabel("Sample plate")).toContainText("Heater-Shaker", {
    timeout: 30_000,
  });
  await expect(page.getByLabel("Sample plate")).toContainText("60 °C");
  await expect(
    page.getByRole("button", {
      name: "Slot C1: Heater-Shaker with Destination wells",
    }),
  ).toBeVisible();
});
