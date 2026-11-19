import { expect, test } from "@playwright/test";

test("a marketplace paper becomes an adjustable cloud lab workflow", async ({
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
  await page
    .getByRole("button", { name: "Workflow marketplace", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Explore When pipetting is not the answer" })
    .click();

  // Each step of the paper is read onto twins that can do it, beyond the liquid handler.
  const section = page.getByRole("region", { name: "Reproduce on the twins" });
  await expect(section.getByText("4 of 4 steps on a twin")).toBeVisible();
  const step = (n: number) => section.getByTestId(`paper-step-${n}`);
  await expect(step(2).getByLabel("Instrument for step 2")).toHaveValue(
    "chemlab:retsch_pm100",
  );
  await expect(step(4).getByLabel("Instrument for step 4")).toHaveValue(
    "chemlab:rigaku_miniflex600_external_cooling",
  );
  // A paper condition beyond the teaching twins is said, not hidden.
  await expect(step(3)).toContainText("so the template uses 120 °C");

  // The learner swaps the furnace and leaves the diffraction step out.
  await step(3)
    .getByLabel("Instrument for step 3")
    .selectOption("chemlab:carbolite_tf1_12_60_300");
  await step(4).getByLabel("Instrument for step 4").selectOption("");
  await expect(section.getByText("3 of 4 steps on a twin")).toBeVisible();

  await section
    .getByRole("button", { name: "Open as a cloud lab workflow" })
    .click();
  const studio = page.getByTestId("cloudlab-workflow");
  await expect(studio.getByLabel("Workflow name")).toHaveValue(
    "When pipetting is not the answer",
  );
  await expect(studio.getByText("Unsaved changes")).toBeVisible();
  await expect(studio.getByLabel("Step 1 instrument")).toHaveValue(
    "chemlab:mt_quantos_q2_xpe206dr",
  );
  await expect(studio.getByLabel("Step 5 instrument")).toHaveValue(
    "chemlab:carbolite_tf1_12_60_300",
  );
  await expect(studio.getByLabel("Step 5 temperature")).toHaveValue("120");
  await expect(studio.getByText("Every step fits")).toBeVisible();

  // The template runs as a synthetic teaching simulation and is saved with it.
  await studio.getByRole("button", { name: "Run teaching simulation" }).click();
  await expect(
    studio.getByRole("region", { name: "Run result" }),
  ).toBeVisible();
  await expect(studio.getByText("Saved")).toBeVisible();
  await page.reload();
  await expect(studio.getByLabel("Step 5 instrument")).toHaveValue(
    "chemlab:carbolite_tf1_12_60_300",
  );
  expect(errors).toEqual([]);
});
