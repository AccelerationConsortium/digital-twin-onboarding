import { expect, test, type Page } from "@playwright/test";

async function openDrills(page: Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "This is my first time" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.goto("/#/learn/intermediate");
  await page.getByRole("button", { name: "Open fault drills" }).click();
  await expect(
    page.getByRole("heading", { name: "Fault drills" }),
  ).toBeVisible();
}

async function practise(page: Page, instrument: string, fault: string) {
  const form = page.getByRole("form", { name: "Practise a drill" });
  await form
    .getByLabel("Instrument", { exact: true })
    .selectOption({ label: instrument });
  await form
    .getByLabel("Fault", { exact: true })
    .selectOption({ label: fault });
  await form.getByRole("button", { name: "Start the drill" }).click();
}

test("a learner responds to an instrument fault mid-run, then sits a checkride", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await openDrills(page);

  // 1 · The run goes on the twin; nothing can be done until the fault fires.
  await practise(
    page,
    "Liquid handler",
    "Tips run out or a tip is not picked up",
  );
  const drill = page.getByRole("region", { name: "Drill" });
  await expect(drill.getByRole("status")).toHaveText("Running on the twin");
  await expect(
    drill.getByRole("list", { name: "Run" }).getByRole("listitem"),
  ).toHaveCount(4);
  await expect(
    drill.getByRole("button", { name: "Pause the run" }),
  ).toHaveCount(0);
  const alarm = drill.getByRole("alert");
  await expect(alarm).toContainText("stops at step 4", { timeout: 10_000 });
  await expect(alarm.getByLabel("Time left")).toContainText("s");

  // 2 · The recovery, in order, then resume.
  for (const action of [
    "Pause the run",
    "Load a full tip rack in the tip slot",
    "Confirm the new rack so the instrument's tip count starts again",
  ])
    await drill.getByRole("button", { name: action }).click();
  await expect(
    drill.getByRole("list", { name: "Your response" }),
  ).toContainText("Pause the run");
  await drill.getByRole("button", { name: "Resume the run" }).click();
  const last = page.getByRole("region", { name: "Last drill" });
  await expect(last).toContainText("Passed");
  await expect(last).toContainText("No unsafe action.");
  await expect(last).toContainText("The recovery was in the right order.");
  // The same fault, as the mock connector refuses it for an agent.
  await last.getByText("What an agent sees for this fault").click();
  await expect(last).toContainText("has run out of Pipette tips");
  await expect(page.getByLabel("Your results")).toContainText("Passed1 / 1");

  // 3 · An unsafe action and the wrong ending are recorded.
  await practise(
    page,
    "Sample transfer robot",
    "The arm collides or makes a protective stop",
  );
  await expect(drill.getByRole("alert")).toContainText("protective stop", {
    timeout: 10_000,
  });
  await drill
    .getByRole("button", { name: "Jog the arm free yourself" })
    .click();
  await drill.getByRole("button", { name: "Resume the run" }).click();
  await expect(last).toContainText("Not passed");
  await expect(last).toContainText("1 unsafe action.");
  await expect(last).toContainText("Stop the run and call the operator");

  // 4 · A checkride: three drills, no answers until the last one ends.
  await page
    .getByRole("region", { name: "Checkride" })
    .getByRole("button", { name: "Take the checkride" })
    .click();
  for (const n of [1, 2, 3]) {
    if (n > 1)
      await page.getByRole("button", { name: "Start the next drill" }).click();
    const step = page.getByRole("region", { name: `Checkride drill ${n}` });
    await expect(step.getByRole("alert")).toBeVisible({ timeout: 10_000 });
    await step
      .getByRole("button", { name: "Stop the run and call the operator" })
      .click();
    if (n < 3)
      await expect(page.getByRole("status")).toHaveText(
        "Drill recorded. Results come at the end of the checkride.",
      );
  }
  const ride = page.getByRole("region", { name: "Last checkride" });
  await expect(ride).toContainText("Checkride not passed");
  await expect(ride.getByRole("listitem")).toHaveCount(3);

  // 5 · A lab's incident drills; only operators add them.
  const lab = page.getByRole("region", { name: "Lab drills" });
  await expect(lab).toContainText("This lab has no drills yet.");
  await expect(lab).toContainText(
    "Adding a drill from an incident needs the lab operator role.",
  );
  await expect(page.getByText("Synthetic teaching model.")).toBeVisible();
});
