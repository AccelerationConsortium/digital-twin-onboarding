import { expect, test } from "@playwright/test";

test("a learner predicts, names and repairs an injected fault", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "This is my first time" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.goto("/#/learn/intermediate");
  await page.getByRole("button", { name: "Open fault practice" }).click();
  await expect(
    page.getByRole("heading", { name: "Find the fault" }),
  ).toBeVisible();

  await page
    .getByRole("button", { name: "Start with the first workflow" })
    .click();
  const exercise = page.getByRole("region", { name: "Workflow 1" });
  await expect(exercise).toContainText("Transfer 100 µL into A1");
  // The answer is not on the page before the learner commits to one.
  await expect(exercise).not.toContainText("before any tip");

  // 1 · A wrong prediction is recorded as wrong.
  await exercise.getByLabel("Yes, every step runs").check();
  await exercise.getByRole("button", { name: "Record my prediction" }).click();

  // 2 · The cause is one of four.
  await expect(exercise.getByRole("radio")).toHaveCount(4);
  await exercise
    .getByLabel("A step uses the pipette before any tip is picked up.")
    .check();
  await exercise.getByRole("button", { name: "Record my answer" }).click();
  await expect(exercise).toContainText("It stops at step 1.");
  await expect(exercise).toContainText("You predicted otherwise.");
  await expect(exercise).toContainText("You named it.");

  // 3 · An unchanged workflow is still broken.
  await exercise.getByRole("button", { name: "Check my repair" }).click();
  await expect(exercise.getByRole("status")).toHaveText(
    "The workflow still stops at step 1.",
  );

  // Repair it in the studio: the missing pick-up goes first.
  await exercise.getByRole("button", { name: "Open the workflow" }).click();
  await expect(page.getByTestId("workflow-studio")).toBeVisible({
    timeout: 30_000,
  });
  await page
    .getByRole("group", { name: "Add a workflow block" })
    .getByRole("button", { name: "Add pick up tip block" })
    .click();
  for (const from of [4, 3, 2])
    await page.getByRole("button", { name: `Move step ${from} up` }).click();
  await expect(page.getByLabel("Step 1 action")).toHaveValue("pickup");
  await page.getByRole("button", { name: /Save/ }).first().click();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();

  await page.goto("/#/practice");
  await page
    .getByRole("region", { name: "Workflow 1" })
    .getByRole("button", { name: "Check my repair" })
    .click();
  const finished = page.getByRole("list", { name: "Finished workflows" });
  await expect(finished).toContainText("Repaired in 2 tries");
  const results = page.getByLabel("Your results");
  await expect(results).toContainText("Predicted0 / 1");
  await expect(results).toContainText("Cause named1 / 1");
  await expect(
    page.getByRole("button", { name: "Next workflow" }),
  ).toBeVisible();
});
