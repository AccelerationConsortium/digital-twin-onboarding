import { expect, test, type Page } from "@playwright/test";

// Set SHOTS to a folder to keep a screenshot of each stage.
const shot = async (page: Page, name: string) => {
  if (process.env.SHOTS)
    await page.screenshot({
      path: `${process.env.SHOTS}/${name}.png`,
      fullPage: true,
    });
};

async function step(
  page: Page,
  n: number,
  kind: string,
  volume?: number,
  well?: string,
) {
  await page.getByLabel(`Step ${n} action`).selectOption(kind);
  if (volume !== undefined)
    await page.getByLabel(`Step ${n} volume in µL`).fill(String(volume));
  if (well) await page.getByLabel(`Step ${n} well`).selectOption(well);
}

test("a new learner trains on the Flex and a mock portal reads the record", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();

  await page.getByRole("button", { name: "Cloud lab onboarding" }).click();
  await expect(
    page.getByRole("heading", { name: "Cloud lab onboarding" }),
  ).toBeVisible();
  await shot(page, "1-start");
  await page.getByRole("button", { name: "Start training" }).click();

  // Learn: one wrong answer first, then all right.
  await page.getByLabel("Into the waste chute in D3").check();
  await page.getByLabel("300 µL").first().check();
  await page.getByLabel("2,000 µL").nth(1).check();
  await page.getByLabel("It picks up a tip").check();
  await page.getByRole("button", { name: "Check answers" }).click();
  await expect(page.getByText("1 not right yet")).toBeVisible();
  await shot(page, "2-learn");
  await page.getByLabel("1,000 µL").check();
  await page.getByRole("button", { name: "Check answers" }).click();
  await page.getByRole("button", { name: "Next: repair a workflow" }).click();

  // Repair: the injected fault stops, and trimming steps does not count.
  await page.getByRole("button", { name: "Run dry check" }).click();
  await expect(page.getByText("when the tip has room for 0 µL")).toBeVisible();
  await shot(page, "3-fault");
  await step(page, 2, "aspirate", 600);
  await step(page, 3, "dispense", 600, "A1");
  await step(page, 4, "aspirate", 600, "stock");
  await page.getByRole("button", { name: "Run dry check" }).click();
  await expect(page.getByText("reaches the goal")).toBeVisible();
  await shot(page, "4-repaired");
  await page.getByRole("button", { name: "Next: write your own" }).click();

  // Write: a fresh tip for each of three wells.
  for (const [i, well] of ["A1", "A2", "A3"].entries()) {
    for (const kind of ["Pick up tip", "Aspirate", "Dispense", "Drop tip"])
      await page.getByRole("button", { name: kind, exact: true }).click();
    await step(page, i * 4 + 2, "aspirate", 250, "stock");
    await step(page, i * 4 + 3, "dispense", 250, well);
  }
  await page.getByRole("button", { name: "Run dry check" }).click();
  await expect(page.getByText("reaches the goal")).toBeVisible();
  await page.getByRole("button", { name: "Next: your record" }).click();
  await expect(
    page.getByRole("heading", { name: "Your training record" }),
  ).toBeVisible();
  await shot(page, "5-record");

  // The mock portal reads only the attached record and sends it to operator review.
  await page.getByRole("button", { name: "Attach to a run request" }).click();
  await expect(
    page.getByRole("heading", { name: "Request a run" }),
  ).toBeVisible();
  await expect(page.getByText("Every training task passed")).toBeVisible();
  await shot(page, "6-portal");
  await page
    .getByRole("button", { name: "Submit for operator review" })
    .click();
  await expect(
    page.getByText("Ready for operator safety review"),
  ).toBeVisible();
  await shot(page, "7-review");

  // Phone width: the repair step still fits without sideways scrolling.
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole("button", { name: "Back to training" })
    .or(page.getByRole("button", { name: "Cloud lab onboarding" }))
    .first()
    .click();
  await page.getByRole("button", { name: /Repair/ }).click();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await shot(page, "8-phone");
});
