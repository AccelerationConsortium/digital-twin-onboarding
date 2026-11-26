import { expect, test, type Page } from "@playwright/test";

async function enter(page: Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
}

type Plan = {
  digest: string;
  devices: { id: string; connector: string | null }[];
  connectors: Record<string, { features: Record<string, string> }>;
  steps: { id: string; device: string; command: string; world: object }[];
};

/** What the runner reports for a plan whose every command was accepted. */
function passed(plan: Plan) {
  return {
    schema: "simreal.report/1",
    evidence: "simulation",
    plan_digest: plan.digest,
    outcome: "passed",
    stopped_at: null,
    reason: null,
    started_at: 1,
    wall_s: 21.5,
    connectors: Object.fromEntries(
      plan.devices
        .filter((device) => device.connector)
        .map((device) => [
          device.id,
          {
            connector: device.connector,
            package_version: "0.1.0",
            commit: null,
            dirty: null,
            features: plan.connectors[device.connector!].features,
          },
        ]),
    ),
    steps: plan.steps.map((step) => ({
      id: step.id,
      cycle: 1,
      device: step.device,
      command: step.command,
      status: "done",
      wall_s: 0.2,
      ...(step.command === "RunContinuousMotion" && { device_s: 20 }),
    })),
    cycles: [
      { cycle: 1, steps: plan.steps.length, wall_s: 4.8, device_s: 144.6 },
    ],
    world: plan.steps[plan.steps.length - 1].world,
  };
}

test("a workflow is checked against the connectors and its run is kept", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await enter(page);
  await page.getByRole("button", { name: "Connector simulation" }).click();
  await expect(page).toHaveURL(/#\/sim-real$/);
  await expect(page.getByRole("heading", { name: "Sim–Real" })).toBeVisible();
  await expect(
    page.getByText("Connector simulation · no hardware"),
  ).toBeVisible();

  // Both connectors are listed with the commands their pinned releases define.
  const connectors = page.getByRole("region", { name: "Connectors" });
  await expect(
    connectors.getByRole("heading", { name: "Opentrons Flex" }),
  ).toBeVisible();
  const arm = connectors.getByRole("article").filter({ hasText: "UR5e arm" });
  await arm.locator("summary").click();
  await expect(arm.getByText("PlateGripperController")).toBeVisible();
  await expect(arm.getByText("GripPlate")).toBeVisible();
  await expect(
    arm.getByText("WidthMillimeters: Real (60–140 mm)"),
  ).toBeVisible();

  // A value outside the connector's own limit is named before anything runs.
  const editor = page.getByLabel("Workflow JSON");
  const example = JSON.parse(await editor.inputValue());
  const hot = structuredClone(example);
  hot.steps[0].parameters.Temperature = 150;
  await editor.fill(JSON.stringify(hot));
  await page.getByRole("button", { name: "Check workflow" }).click();
  const problems = page.getByRole("region", { name: "Why it would not run" });
  await expect(
    problems.getByText("Temperature must be at most 95 °C; got 150"),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Download plan" })).toHaveCount(
    0,
  );
  await expect(page.getByText("Check the workflow first.")).toBeVisible();

  // The example compiles into the arm's and the Flex's own commands.
  await editor.fill(JSON.stringify(example, null, 2));
  const answered = page.waitForResponse("**/api/sim-real/v1/compile");
  await page.getByRole("button", { name: "Check workflow" }).click();
  const plan: Plan = await (await answered).json();
  const shown = page.getByRole("region", { name: "Plan" });
  await expect(shown).toBeVisible({ timeout: 120_000 });
  await expect(
    shown.getByRole("row", { name: /to-reader\.grip .*GripPlate/ }),
  ).toContainText("assay-plate: arm gripper");
  await expect(
    shown.getByRole("row", {
      name: /to-reader\.release-ledger .*ReleaseLabware/,
    }),
  ).toBeVisible();
  await expect(
    shown.getByRole("row", { name: /to-reader\.scene/ }),
  ).toContainText("(simulation only)");
  await expect(
    shown.getByRole("row", { name: /to-flex\.register-ledger/ }),
  ).toContainText("assay-plate: flex D1");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download plan" }).click();
  expect((await download).suggestedFilename()).toBe("plan.json");

  // A report for another plan is refused; this plan's report is kept and survives a reload.
  const runs = page.getByRole("region", { name: "Runs" });
  const report = passed(plan);
  const upload = (body: object) =>
    runs.getByLabel("Keep a run report").setInputFiles({
      name: "report.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(body)),
    });
  await upload({ ...report, plan_digest: "0".repeat(64) });
  await expect(page.getByRole("alert")).toHaveText(
    "The report is for another plan",
  );
  // The arm's gripper is simulated, so this plan has no run on instruments; a report
  // that claims one is not kept as a simulated run.
  await expect(
    runs.getByText("UR5e arm runs only in simulation."),
  ).toBeVisible();
  await upload({ ...report, evidence: "instrument" });
  await expect(page.getByRole("alert")).toHaveText(
    "Only simulated runs are kept here; this report is not one",
  );
  await upload(report);
  await expect(runs.getByRole("list", { name: "Kept runs" })).toContainText(
    "passed",
  );
  await expect(
    runs.getByRole("row", { name: /to-reader\.grip .*GripPlate/ }),
  ).toContainText("done");
  await expect(runs.getByText("144.6 s").first()).toBeVisible();

  await page.reload();
  const kept = page
    .getByRole("region", { name: "Runs" })
    .getByRole("list", { name: "Kept runs" })
    .getByRole("button");
  await expect(kept).toHaveCount(1);
  await kept.click();
  await page.getByRole("button", { name: "Delete this run" }).click();
  await expect(kept).toHaveCount(0);

  // A plan of the Flex alone can go on to the Flex itself, from where it is installed.
  const alone = structuredClone(example);
  alone.devices = [example.devices[0]];
  alone.layout.placements = [];
  alone.labware = [];
  alone.steps = [example.steps[0]];
  await page.getByLabel("Workflow JSON").fill(JSON.stringify(alone));
  await page.getByRole("button", { name: "Check workflow" }).click();
  const instrument = page.getByRole("region", { name: "Runs" });
  await expect(
    instrument.getByRole("heading", { name: "On the instrument" }),
  ).toBeVisible();
  await expect(
    instrument.getByText(
      "academy-sim-real run plan.json --real flex=<address> --report report.json",
    ),
  ).toBeVisible();
});
