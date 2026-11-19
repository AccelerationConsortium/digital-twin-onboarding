import { expect, test } from "@playwright/test";

test("module unit operations open a Flex studio with their modules and run", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();

  for (const [operation, slot, plate] of [
    ["mix", "Slot C1: Heater-Shaker", "Deck"],
    ["incubate", "Slot A1: Temperature Module", "Deck"],
    ["move labware", "Slot A1: Temperature Module", "Deck"],
    ["read a plate", "Slot B3: Plate reader", "Deck"],
  ] as const) {
    await page.goto("/#/instruments");
    await page
      .getByRole("button", { name: `Practise ${operation}`, exact: true })
      .click();
    const studio = page.getByTestId("workflow-studio");
    await expect(studio).toBeVisible({ timeout: 30_000 });
    await expect(studio).toHaveAttribute("data-instrument", "flex");
    const modules = page.getByRole("group", { name: "Deck modules" });
    await expect(
      modules.getByRole("button", { name: /Gripper/ }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: slot })).toBeVisible();
    await page.getByRole("button", { name: "Run teaching simulation" }).click();
    await expect(studio.getByText("Sequence completed").first()).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByLabel("Sample plate")).toContainText(plate);
    if (operation === "read a plate")
      await expect(page.getByLabel("Sample plate")).toContainText("read:");
  }

  // Thermal cycling and magnetic separation still have no module in the twin.
  await page.goto("/#/instruments");
  await expect(page.getByText("Not in the teaching model yet")).toHaveCount(2);
});
