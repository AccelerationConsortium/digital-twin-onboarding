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
  await page
    .getByRole("button", { name: "Next: record your assumptions" })
    .click();

  // The steps the GASE Guidelines add: assumptions, escalation, acceptance,
  // the deviation write-up and whether to automate at all.
  const pick = (group: string, option: string) =>
    page
      .getByRole("group", { name: group })
      .getByLabel(option, { exact: true })
      .check();
  const relies =
    "Which of these does that result depend on? Choose every one that applies.";
  for (const option of [
    "The stock reservoir holds at least 1,200 µL when the run starts",
    "A1 and A2 are empty when the run starts",
    "There is at least one 1000 µL tip in B1",
  ])
    await pick(relies, option);
  await page.getByRole("button", { name: "Check answers" }).click();
  await expect(page.getByText("1 not right yet")).toBeVisible();
  await pick(
    relies,
    "The liquid behaves like water, so the pipette's volumes are accurate",
  );
  await page.getByRole("button", { name: "Check answers" }).click();
  await page
    .getByRole("button", { name: "Next: know when to escalate" })
    .click();
  await pick(
    "What do you do?",
    "Stop, and escalate to the method owner with the check result",
  );
  await page.getByRole("button", { name: "Check answers" }).click();
  await page.getByRole("button", { name: "Next: judge the results" }).click();
  await pick("Is the accuracy criterion met?", "Met");
  await pick("Is the precision (CV) criterion met?", "Not met");
  await pick(
    "Is the automated method equivalent to the manual one?",
    "No: one criterion fails, so it is not equivalent yet",
  );
  await page.getByRole("button", { name: "Check answers" }).click();
  await page
    .getByRole("button", { name: "Next: write up the deviation" })
    .click();
  await pick("Which step of the original workflow failed first?", "Step 3");
  await pick(
    "What was expected at that step?",
    "The tip to hold all the liquid drawn so far",
  );
  await pick(
    "What was done about it?",
    "The load was split into two trips and the workflow checked again",
  );
  await page
    .getByLabel("Note for a colleague")
    .fill("Step 3 drew 1,200 µL into a 1,000 µL tip; split into two trips.");
  await page.getByRole("button", { name: "Check answers" }).click();
  await page
    .getByRole("button", { name: "Next: decide whether to automate" })
    .click();
  await pick(
    "About how many hours of hands-on time a week would automation save?",
    "About 23",
  );
  await pick(
    "What is the cost of not automating?",
    "About 30 hours a week of manual effort and the rework of redone plates",
  );
  await pick(
    "What do you recommend?",
    "Automate, and check the setup time against the weekly saving first",
  );
  await page.getByRole("button", { name: "Check answers" }).click();
  await shot(page, "5a-decide");
  await page.getByRole("button", { name: "Next: your record" }).click();
  await expect(
    page.getByText(
      "Escalates a problem the procedure does not cover instead of improvising",
    ),
  ).toBeVisible();
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
  await expect(
    page.getByText("Checked in this browser with the Academy's public key."),
  ).toBeVisible();
  await shot(page, "6-portal");
  await page
    .getByRole("button", { name: "Submit for operator review" })
    .click();
  await expect(
    page.getByText("Ready for operator safety review"),
  ).toBeVisible();
  await shot(page, "7-review");

  // An edited record fails the signature check before any policy applies.
  const envelope = await (
    await page.request.get("/api/cloudlab/qualifications/me")
  ).json();
  const record = JSON.parse(
    Buffer.from(envelope.payload, "base64url").toString(),
  );
  record.expires_at = "2099-01-01T00:00:00+00:00";
  const edited = {
    ...envelope,
    payload: Buffer.from(JSON.stringify(record)).toString("base64url"),
  };
  await page.locator('input[type="file"]').setInputFiles({
    name: "edited.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(edited)),
  });
  await expect(
    page.getByText("This request cannot be submitted yet"),
  ).toBeVisible();
  await expect(
    page.getByText("The signature does not match: edited, or not issued here"),
  ).toBeVisible();
  await shot(page, "7b-edited");

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
