import { expect, test } from "@playwright/test";

test("every cloud lab instrument has a teaching page", async ({ page }) => {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.goto("/#/instruments");

  const section = page.getByRole("region", { name: "In a cloud lab" });
  await section.getByRole("button", { name: /Multimode plate reader/ }).click();
  await page.getByRole("button", { name: "Learn to use it" }).click();
  await expect(page).toHaveURL(/#\/instruments\/plate-reader$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Multimode plate reader" }),
  ).toBeVisible();
  await expect(page.getByText(/Shines light through each well/)).toBeVisible();

  // The steps come from the twin; pressing one shows it on the model.
  const use = page.getByRole("tabpanel");
  const load = use.getByRole("button", { name: /Load Put a plate in/ });
  await expect(load).toContainText("Through the front, left, 0.07 m above");
  await load.click();
  await expect(load).toHaveAttribute("aria-pressed", "true");
  await expect(
    page
      .getByRole("group", { name: "State" })
      .getByRole("button", { name: "Carrier out" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByText(/carrier slides out of the lower left/),
  ).toBeVisible();

  await page.getByRole("tab", { name: "Parts" }).click();
  await page.getByRole("tabpanel").getByRole("button", { name: /Lid/ }).click();
  await expect(
    page.getByText(
      "Lid: Opens the chamber for service; plates go in on the carrier.",
    ),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Details" }).click();
  await expect(page.getByText("What the cloud lab publishes")).toBeVisible();
  await expect(page.getByText(/MBZUAI, CC-BY-NC-4\.0/)).toBeVisible();
  await expect(
    page.getByText(/not this instrument's specification/),
  ).toBeVisible();
  if (process.env.SHOTS)
    await page.screenshot({ path: `${process.env.SHOTS}/lesson.png` });

  // The reader is a workflow step, so the page links to the workflow, not a copy of it.
  await page
    .getByRole("button", { name: "Use it in a cloud lab workflow" })
    .click();
  await expect(page).toHaveURL(/#\/cloudlab-workflow$/);
  await page.goBack();
  await expect(
    page.getByRole("heading", { level: 1, name: "Multimode plate reader" }),
  ).toBeVisible();

  // An estimated box teaches from its twin's values without a model.
  await page.goto("/#/instruments/nmr");
  await expect(
    page.getByRole("heading", { level: 1, name: "500 MHz NMR spectrometer" }),
  ).toBeVisible();
  await expect(
    page.getByText("No 3D model; the twin is one estimated box."),
  ).toBeVisible();
  await expect(page.getByRole("tab", { name: "Parts" })).toHaveCount(0);
  await expect(
    page.getByText("Put up to 96 tubes in, each up to 1.5 mL."),
  ).toBeVisible();
  await page.getByRole("button", { name: /Next/ }).click();
  await expect(page).toHaveURL(/#\/instruments\/dls-plate-reader$/);
  await page
    .getByRole("button", { name: "Meet the instruments" })
    .first()
    .click();
  await expect(
    page.getByRole("region", { name: "In a cloud lab" }),
  ).toBeVisible();
});
