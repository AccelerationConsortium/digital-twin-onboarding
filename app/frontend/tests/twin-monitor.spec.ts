import { expect, test } from "@playwright/test";

test("the twin runs ahead of a mock run, pauses on a divergence and replays a fix", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "This is my first time" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.goto("/#/plan");
  await page.getByRole("tab", { name: "1 · Describe" }).click();
  await page
    .getByRole("region", { name: "Example workcells" })
    .getByRole("button", { name: /Flex, plate sealer, plate reader/ })
    .click();
  await expect(page.getByRole("tab", { name: "4 · Layout" })).toHaveAttribute(
    "aria-selected",
    "true",
    { timeout: 60_000 },
  );

  // Four mixes on the Flex, each using one tip.
  const catalog = await (await page.request.get("/api/twins")).json();
  const [load, mix, ...rest] = catalog.steps;
  const saved = await page.request.put("/api/twins/workflow", {
    data: {
      expected_version: catalog.version,
      steps: [load, mix, mix, mix, mix, ...rest],
    },
  });
  expect(saved.ok()).toBeTruthy();
  await page.reload();
  await page.getByRole("tab", { name: "3 · Workflow" }).click();

  const monitor = page.getByRole("region", { name: "Run with the twin ahead" });
  await monitor
    .getByLabel("Mock fault")
    .selectOption({ label: "Rack holds fewer than declared" });
  await monitor.getByLabel(/Actually in the rack/).fill("3");
  await monitor.getByRole("button", { name: "Prepare monitored run" }).click();
  const run = monitor.getByLabel("Monitored run");
  await expect(run.getByText("Step 0/9 · ready")).toBeVisible({
    timeout: 30_000,
  });
  await expect(run.getByText("Synthetic · in-process-mock")).toBeVisible();
  const ghost = run.getByRole("figure", { name: "Next move" });
  await expect(ghost.getByText(/Next · Step 1 · Load sample/)).toBeVisible();

  // The rack is counted on first use: the twin expected 95 tips, the mock has 2.
  await run.getByRole("button", { name: "Run to the end" }).click();
  const paused = run.getByRole("status", { name: "Run paused" });
  await expect(paused.getByText("Twin and executor differ")).toBeVisible({
    timeout: 30_000,
  });
  const row = paused.getByRole("row", { name: /Pipette tips/ });
  await expect(row.getByRole("cell", { name: "95" })).toBeVisible();
  await expect(row.getByRole("cell", { name: "2", exact: true })).toBeVisible();
  await expect(run.getByText("Step 2/9 · paused")).toBeVisible();

  // Synced, the twin predicts the stop three steps ahead and runs up to it.
  await run.getByRole("button", { name: "Resume" }).click();
  await expect(run.getByText(/Predicted stop at step 5/)).toBeVisible();
  await run.getByRole("button", { name: "Run to the end" }).click();
  await expect(run.getByText("Step 4/9 · blocked")).toBeVisible({
    timeout: 30_000,
  });
  await expect(paused.getByText("Twin lookahead")).toBeVisible();
  await expect(paused.getByText(/run out of Pipette tips/)).toBeVisible();
  await expect(run.getByRole("button", { name: "Next step" })).toBeDisabled();

  // Replayed with a full rack, the same run would have completed.
  await run.getByText("Replay with changes").click();
  await run
    .getByLabel(/Liquid handler \(Opentrons Flex\) · Pipette tips/)
    .fill("96");
  await run.getByRole("button", { name: "Replay in the twin" }).click();
  await expect(
    run.getByText("With these changes the run completes."),
  ).toBeVisible({ timeout: 60_000 });
  await page.screenshot({
    path: "/tmp/academy-twin-monitor.png",
    fullPage: true,
  });

  // Phone width: the run stays readable without sideways scrolling.
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(run.getByText("Step 4/9 · blocked")).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});
