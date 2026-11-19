import { expect, test } from "@playwright/test";

test("a learner chains cloud lab instruments into a workflow", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.goto("/#/instruments");
  await page
    .getByRole("button", { name: /Chain cloud lab instruments/ })
    .click();

  const studio = page.getByTestId("cloudlab-workflow");
  await expect(
    studio.getByRole("heading", { name: "Cloud lab workflow." }),
  ).toBeVisible();
  await expect(studio.getByText("Synthetic teaching model")).toBeVisible();
  const add = (name: string) =>
    studio.getByRole("button", { name: `Add a ${name} step` }).click();
  const step = (n: number) => studio.getByTestId(`cloudlab-step-${n}`);

  // The plate starts on the liquid handler and visits each instrument for what it does.
  await add("Robotic sample preparation workcell");
  await expect(step(1).getByLabel("Step 1 action")).toHaveValue("load");
  await step(1).getByLabel("Step 1 volume").fill("200");
  await add("Robotic sample preparation workcell");
  await expect(step(2).getByLabel("Step 2 action")).toHaveValue("mix");
  await add("Workcell cell incubator");
  await expect(step(3).getByLabel("Step 3 action")).toHaveValue("transfer");
  await step(3).getByLabel("Step 3 slot").selectOption("4");
  await add("Workcell cell incubator");
  await expect(step(4).getByLabel("Step 4 action")).toHaveValue("heat");
  await step(4).getByLabel("Step 4 temperature").fill("60");
  // Outside what the incubator twin holds: the step says why, and the run waits.
  await expect(step(4)).toHaveAttribute("aria-invalid", "true");
  await expect(step(4).getByRole("alert")).toContainText("33–50 °C");
  await expect(
    studio.getByRole("button", { name: "Run teaching simulation" }),
  ).toBeDisabled();
  await expect(studio.getByText("Change step 4 first.")).toBeVisible();
  await step(4).getByLabel("Step 4 temperature").fill("37");
  await expect(step(4)).not.toHaveAttribute("aria-invalid");

  await add("Multimode plate reader");
  await expect(step(5).getByLabel("Step 5 action")).toHaveValue("transfer");
  await add("Multimode plate reader");
  await expect(step(6).getByLabel("Step 6 action")).toHaveValue("read");

  // A plate cannot go onto the flash system's tube rack.
  await add("Flash chromatography system");
  await expect(step(7).getByRole("alert")).toContainText(
    "accepts a tube, not a plate",
  );
  await step(7).getByRole("button", { name: "Delete step 7" }).click();
  await expect(studio.getByText("Every step fits")).toBeVisible();

  const flow = studio.getByRole("region", { name: "Flow", exact: true });
  await expect(flow.getByRole("listitem")).toHaveCount(3);
  await expect(
    flow.getByRole("listitem", { name: "Workcell cell incubator" }),
  ).toContainText("4 Hold temperature");
  // The plate has moved on, so every incubator slot is free again.
  await expect(
    flow.getByRole("img", { name: "0 of 20 slots in use" }),
  ).toBeVisible();
  await expect(
    flow.getByRole("img", { name: "1 of 1 slots in use" }),
  ).toBeVisible();
  await expect(flow.getByText("95 pipette tips left")).toBeVisible();

  await studio.getByLabel("Workflow name").fill("Viability readout");
  await studio.getByRole("button", { name: "Run teaching simulation" }).click();
  const result = studio.getByRole("region", { name: "Run result" });
  await expect(result.getByRole("listitem")).toHaveCount(6);
  await expect(
    result.getByText(/^Synthetic readout: 200 µL · 37 °C/),
  ).toBeVisible();
  await expect(studio.getByRole("status")).toContainText("Saved");
  if (process.env.SHOTS)
    await studio.screenshot({
      path: `${process.env.SHOTS}/cloudlab-workflow.png`,
    });

  // The saved workflow is the learner's own and comes back from the sidebar.
  await page.reload();
  await page.getByRole("button", { name: "Cloud lab workflow" }).click();
  await expect(studio.getByLabel("Workflow name")).toHaveValue(
    "Viability readout",
  );
  await expect(studio.getByTestId(/^cloudlab-step-/)).toHaveCount(6);
  await expect(step(3).getByLabel("Step 3 slot")).toHaveValue("4");
});
