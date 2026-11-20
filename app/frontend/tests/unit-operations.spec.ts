import { expect, test } from "@playwright/test";

test("a workflow is composed from the unit operation table and runs on mock connectors", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "This is my first time" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.goto("/#/plan/instruments");
  const studio = page.getByRole("region", { name: "Plan a workcell" });
  for (const name of ["Heating station", "Plate reader", "Transfer robot"]) {
    await page.getByRole("button", { name, exact: true }).click();
  }
  const confirm = studio.getByRole("button", { name: "Confirm twin" });
  for (let i = 3; i > 0; i--) {
    await confirm.first().click();
    await expect(confirm).toHaveCount(i - 1);
  }

  await page.getByRole("tab", { name: "3 · Workflow" }).click();
  const table = studio.getByRole("group", { name: "Unit operations" });
  await expect(table).toBeVisible();
  // Without a connector command the operation stays in the table, unavailable.
  await expect(
    table.getByRole("button", { name: "Centrifuge: No connector command yet" }),
  ).toBeDisabled();
  await expect(
    studio.getByText("Mock connector", { exact: true }),
  ).toBeVisible();

  await table.getByRole("button", { name: /^Add Load on / }).click();
  await table
    .getByRole("button", { name: "Add Incubate on Heating station" })
    .click();
  await expect(studio.getByLabel("Step 2 temperature")).toHaveValue("37");
  await table.getByRole("button", { name: /^Add Transfer on / }).click();
  await expect(studio.getByLabel("Step 3 to")).toHaveValue(/.+/);
  await table
    .getByRole("button", { name: "Add Absorbance on Plate reader" })
    .click();
  await studio.getByRole("button", { name: "Save workflow" }).click();
  await studio.getByRole("button", { name: "Run on mock connectors" }).click();
  await expect(
    studio.getByText(/4\. Plate reader · Read → .*37 °C/),
  ).toBeVisible();

  if (process.env.SHOTS)
    await table.screenshot({
      path: `${process.env.SHOTS}/unit-operations.png`,
    });
  await page.setViewportSize({ width: 375, height: 812 });
  // The table scrolls inside itself; the page does not scroll sideways.
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});
