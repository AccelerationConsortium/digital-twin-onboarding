import { expect, test } from "@playwright/test";

test("a layout says how precisely each instrument has to be placed", async ({
  page,
}) => {
  test.setTimeout(240_000);
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
    .getByRole("button", { name: /Flex to plate reader/ })
    .click();
  await expect(page.getByRole("tab", { name: "4 · Layout" })).toHaveAttribute(
    "aria-selected",
    "true",
    { timeout: 60_000 },
  );
  await expect(page.getByRole("button", { name: /^Step \d+ · / })).toHaveCount(
    1,
    { timeout: 60_000 },
  );

  const panel = page.getByRole("region", { name: "Placement tolerance" });
  await panel.getByRole("button", { name: "Measure tolerance" }).click();
  // Bands arrive chunk by chunk, tightest instrument first in the table.
  const table = panel.getByRole("table", { name: "Placement requirements" });
  await expect(
    table.getByRole("row", { name: /Liquid handler/ }),
  ).toContainText(/[±≥]\d+ mm/, { timeout: 120_000 });
  await expect(
    table.getByRole("rowheader", { name: "Tool offset" }),
  ).toBeVisible();
  // The allowed region is drawn on the bench around each measured instrument.
  await expect(
    page.locator("svg[aria-label^='Bench top view'] title", {
      hasText: /^Allowed region of /,
    }),
  ).not.toHaveCount(0);
  await panel.screenshot({ path: "/tmp/academy-tolerance-table.png" });
  await panel.getByRole("button", { name: "Stop" }).click();
  await expect(panel.getByRole("button", { name: "Resume" })).toBeVisible();
  await expect(panel.getByRole("progressbar")).toBeVisible();

  // The 1:1 template carries the bands measured so far.
  const download = page.waitForEvent("download");
  await panel.getByRole("button", { name: "Template SVG" }).click();
  expect((await download).suggestedFilename()).toBe("placement-template.svg");

  // A workflow kept for the bench joins later analyses and layout searches.
  await panel.getByText("Bench workflows").click();
  await panel.getByLabel("Kept workflow name").fill("Read once");
  await panel.getByRole("button", { name: "Keep current workflow" }).click();
  await expect(panel.getByText("Read once")).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Keep current workflow" }),
  ).toBeDisabled();
  await expect(
    panel.getByRole("radio", { name: "All 2 on this bench" }),
  ).toBeVisible();
  await expect(page.getByLabel("Every bench workflow")).toBeChecked();
  // Changing the scope starts the analysis over.
  await panel.getByRole("radio", { name: "All 2 on this bench" }).check();
  await expect(
    panel.getByRole("button", { name: "Measure tolerance" }),
  ).toBeVisible();
  await panel.getByRole("button", { name: "Remove Read once" }).click();
  await expect(panel.getByText("Read once")).toHaveCount(0);
  await page.screenshot({
    path: "/tmp/academy-layout-tolerance.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
