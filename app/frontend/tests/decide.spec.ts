import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";

async function openExperiment(page: Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "This is my first time" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.getByRole("button", { name: "Start an experiment" }).click();
}

const run = (page: Page) =>
  page.getByRole("button", { name: "Run experiment", exact: true }).click();
const levers = (page: Page) =>
  page.getByRole("group", { name: "Your next change" });
const call = (page: Page, who: "You" | "Rule") =>
  page.getByRole("group", {
    name: who === "You" ? "Your call" : "The rule's call",
  });

test("a passing run asks for a decision, compares it with the rule, and asks again after reset", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await openExperiment(page);
  await expect(levers(page)).toHaveCount(0);
  await run(page);
  await expect(
    page.getByText("You reached the learning goal.", { exact: true }),
  ).toBeVisible({ timeout: 25000 });
  await expect(page.getByText("How the rule decides")).toHaveCount(0);
  await levers(page).getByRole("button", { name: "Transfer volumes" }).click();
  await expect(
    levers(page).getByRole("button", { name: "Transfer volumes" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    levers(page).getByRole("button", { name: "Starting stock" }),
  ).toBeDisabled();
  await expect(call(page, "Rule")).toContainText("Repeat unchanged");
  await expect(
    page.getByText("Different calls. Weigh the observations below."),
  ).toBeVisible();
  await page.getByText("How the rule decides").click();
  await expect(page.getByText(/self-driving lab/)).toBeVisible();

  await page.getByRole("button", { name: "Reset & try again" }).click();
  await expect(levers(page)).toHaveCount(0);
  await run(page);
  await expect(
    levers(page).getByRole("button", { name: "Repeat unchanged" }),
  ).toBeEnabled({ timeout: 25000 });
  expect(errors).toEqual([]);
});

test("the rule names the lever behind a fault and behind a missed target", async ({
  page,
}) => {
  await openExperiment(page);
  await page.getByRole("button", { name: "Your method" }).click();
  await page
    .getByRole("button", { name: "Delete step 1", exact: true })
    .click();
  await run(page);
  await expect(page.getByText("Step 1: The pipette has no tip.")).toBeVisible();
  await page.getByRole("button", { name: "Observations" }).click();
  await levers(page).getByRole("button", { name: "Tip handling" }).click();
  await expect(call(page, "Rule")).toContainText("Tip handling");
  await expect(page.getByText("Same call.")).toBeVisible();

  await page.getByRole("button", { name: "Reset & try again" }).click();
  await page.getByRole("button", { name: "Lab bench" }).click();
  await page.getByLabel("Diluent volume").fill("150");
  // Restore the deleted pick-up so the run completes and only the ratio is wrong.
  await page.getByRole("button", { name: "Your method" }).click();
  await page.getByRole("button", { name: "Add a step" }).click();
  for (let i = 12; i > 1; i--)
    await page.getByRole("button", { name: `Move step ${i} up` }).click();
  await run(page);
  await expect(
    page.getByText("The sequence finished short of the goal."),
  ).toBeVisible({ timeout: 25000 });
  await levers(page).getByRole("button", { name: "Diluent volume" }).click();
  await expect(call(page, "Rule")).toContainText("Transfer volumes");
  await expect(call(page, "Rule")).toContainText(
    "A 100 µL transfer into 150 µL of diluent is not a 1:2 step.",
  );
});

test("the decision card fits a phone screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openExperiment(page);
  await run(page);
  await levers(page)
    .getByRole("button", { name: "Repeat unchanged" })
    .click({ timeout: 25000 });
  await expect(page.getByText("Same call.")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
