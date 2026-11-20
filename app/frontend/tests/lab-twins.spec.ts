import { expect, test, type Page } from "@playwright/test";

async function enter(page: Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Twin learner");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.getByRole("button", { name: "Learning lab", exact: true }).click();
}

test("beginner sets up a Flex deck, hits a placement rule and runs the transfer", async ({
  page,
}) => {
  await enter(page);
  const twin = page.getByRole("region", { name: "Set up the deck" });
  const tray = twin.getByRole("group", { name: "Labware and modules" });
  await tray.getByRole("button", { name: "Heater-Shaker" }).click();
  await twin.getByRole("button", { name: "Slot B2, empty" }).click();
  await expect(twin.getByText("goes in column 1 or 3")).toBeVisible();
  await expect(
    twin.getByRole("button", { name: "Run the transfer" }),
  ).toBeDisabled();
  for (const [item, slot] of [
    ["Tips", "C1"],
    ["Source", "D1"],
    ["Plate", "D2"],
  ]) {
    await tray.getByRole("button", { name: item }).click();
    await twin.getByRole("button", { name: `Slot ${slot}, empty` }).click();
  }
  await twin.getByRole("button", { name: "Run the transfer" }).click();
  await expect(twin.getByText("Transfer complete.")).toBeVisible({
    timeout: 8000,
  });
  await expect(twin.getByText("Run the transfer · done")).toBeAttached();
  // The deck is a viewer convenience: nothing is saved as an experiment.
  expect(await (await page.request.get("/api/sessions")).json()).toEqual([]);
  await page.reload();
  await expect(
    twin.getByRole("button", { name: "Slot D2, Target plate" }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("intermediate routes a sample through a published lab and advanced sees a connector reject a step", async ({
  page,
}) => {
  await enter(page);
  await page.getByRole("link", { name: "Intermediate", exact: true }).click();
  const floor = page.getByRole("region", { name: "Lay out a published lab" });
  await floor.getByRole("button", { name: "Rainbow", exact: true }).click();
  await floor.getByRole("button", { name: "Use the teaching layout" }).click();
  await floor.getByRole("button", { name: "+ Plate reader" }).click();
  await expect(
    floor.getByText("The paper's sample starts at", { exact: false }),
  ).toBeVisible();
  await floor.getByRole("button", { name: "Clear", exact: true }).click();
  for (const stop of [
    "OT-2 liquid handler",
    "Plate reader",
    "Multi-objective optimizer",
  ])
    await floor.getByRole("button", { name: `+ ${stop}` }).click();
  await floor.getByRole("button", { name: "Run a sample" }).click();
  await expect(floor.getByText("Loop complete.")).toBeVisible({
    timeout: 8000,
  });

  await page.getByRole("link", { name: "Advanced", exact: true }).click();
  const chain = page.getByRole("region", {
    name: "Run unit operations through connectors",
  });
  await chain.getByRole("button", { name: "Move step 2 up" }).click();
  await expect(
    chain.getByText("The plate is on the Heater-Shaker, not the Flex deck."),
  ).toBeVisible();
  await chain.getByRole("button", { name: "Run the chain" }).click();
  await expect(chain.getByText("Stopped at step 2: rejected")).toBeVisible({
    timeout: 8000,
  });
  await expect(page.getByText("Inside a connector")).toBeVisible();
});

test("the simulation lab compares a prediction with the teaching twin's result", async ({
  page,
}) => {
  await enter(page);
  await page
    .getByRole("button", { name: "Simulation lab", exact: true })
    .click();
  const guide = page.getByRole("region", { name: "Simulation steps" });
  await guide.getByLabel("Mixture in A1").fill("40");
  await guide.getByLabel("Tips used").fill("3");
  await page.getByRole("button", { name: "Run mixing experiment" }).click();
  await expect(guide.getByText("A1 · twin reported 40 µL")).toBeVisible({
    timeout: 15000,
  });
  await expect(guide.getByText("Tips · twin reported 4")).toBeVisible();
  await page
    .getByRole("button", { name: "Route a sample through a published lab" })
    .click();
  await expect(page).toHaveURL(/#\/learn\/intermediate$/);
});
