import { expect, test } from "@playwright/test";

test("a learner lights the skill tree from an instrument to a recombined workflow", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.getByRole("button", { name: "Skill tree", exact: true }).click();

  // Stage one: a function is met by having a twin do it.
  const stages = page.getByRole("navigation", { name: "Learning stages" });
  await expect(stages).toContainText("0 / 16 functions met");
  await page.getByRole("button", { name: "Conductivity", exact: true }).click();
  const panel = page.getByRole("region", { name: "Conductivity" });
  await panel.getByRole("button", { name: "Run it on the twin" }).click();
  await expect(panel.getByLabel("What the twin did")).toContainText(
    "synthetic readout",
  );
  await expect(
    page.getByRole("button", { name: "Conductivity, met" }),
  ).toBeVisible();
  await expect(stages).toContainText("1 / 16 functions met");

  // Stage two: a published workflow is a line through prepare, characterize and test.
  const published = page.getByRole("region", { name: "Published workflows" });
  await published
    .getByRole("button", { name: /Find a better electrolyte/ })
    .click();
  await expect(published).toContainText("1 / 3 ready");
  await published
    .getByRole("button", { name: "Reproduce on the twins" })
    .click();
  const bench = page.getByRole("region", { name: "Reproduce on the twins" });
  await expect(bench.getByTestId("paper-step-1")).toContainText("Prepare");
  await expect(bench.getByTestId("paper-step-3")).toContainText("Test");
  await bench
    .getByRole("button", { name: "Open as a cloud lab workflow" })
    .click();
  await page.getByRole("button", { name: "Run teaching simulation" }).click();
  const earned = page
    .getByRole("region", { name: "Run result" })
    .locator("[aria-live]");
  await expect(earned).toContainText("Reproduced Find a better electrolyte");
  await earned.getByRole("button", { name: "See the tree" }).click();
  await expect(
    page.getByRole("navigation", { name: "Learning stages" }),
  ).toContainText("1 / 6 reproduced");

  // Stage three: one paper's preparation, measured the way another paper measures.
  await page
    .getByRole("button", { name: "Simulation lab", exact: true })
    .click();
  const change = page.getByRole("region", { name: "Change it on the twins" });
  await change
    .getByLabel("Measure it like")
    .selectOption({ label: "When pipetting is not the answer" });
  await expect(change.getByTestId("paper-step-3")).toContainText(
    "From When pipetting is not the answer",
  );
  await expect(change.getByTestId("paper-step-3")).toContainText(
    "Characterize",
  );
  await change
    .getByRole("button", { name: "Open as a cloud lab workflow" })
    .click();
  await page.getByRole("button", { name: "Run teaching simulation" }).click();
  await expect(earned).toContainText(
    "Recombined Find a better electrolyte → When pipetting is not the answer",
  );

  // The recombined workflow is saved beside the reproduced one, which is still there.
  const shelf = page.getByLabel("Saved workflow");
  await expect(shelf.locator("option")).toHaveText([
    "Find a better electrolyte · 4 steps",
    "Find a better electrolyte → When pipetting is not the answer · 4 steps",
  ]);
  await shelf.selectOption({ label: "Find a better electrolyte · 4 steps" });
  await expect(page.getByLabel("Workflow name")).toHaveValue(
    "Find a better electrolyte",
  );
  await expect(page.getByText("2 of 12", { exact: true })).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(shelf.locator("option")).toHaveCount(1);
  await expect(page.getByLabel("Workflow name")).toHaveValue(
    "Find a better electrolyte → When pipetting is not the answer",
  );
  expect(errors).toEqual([]);
});
