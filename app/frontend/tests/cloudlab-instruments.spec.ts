import { expect, test } from "@playwright/test";

test("meet the instruments shows what a cloud lab offers", async ({ page }) => {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.goto("/#/instruments");

  const section = page.getByRole("region", { name: "In a cloud lab" });
  await expect(section).toBeVisible();
  await expect(section.getByRole("listitem")).toHaveCount(24);
  await section.getByRole("button", { name: "Separations" }).click();
  await expect(section.getByRole("listitem")).toHaveCount(6);
  await section.getByRole("button", { name: /Analytical HPLC/ }).click();
  const detail = page.getByRole("article", { name: "Analytical HPLC" });
  await expect(detail.getByText("What the cloud lab publishes")).toBeVisible();
  await expect(detail.getByText("ExperimentHPLC")).toBeVisible();
  await expect(detail.getByText(/footprint of a comparable/)).toBeVisible();
  // The stand-in model itself is drawn, not just described.
  await expect(detail.locator("canvas")).toBeVisible();
  if (process.env.SHOTS)
    await section.screenshot({
      path: `${process.env.SHOTS}/meet-cloudlab.png`,
    });

  await section.getByRole("button", { name: "Spectroscopy" }).click();
  await expect(
    section.getByRole("button", { name: /Analytical HPLC/ }),
  ).toHaveCount(0);
  await section.getByRole("button", { name: /Multimode plate reader/ }).click();
  const reader = page.getByRole("article", { name: "Multimode plate reader" });
  await expect(
    reader.getByText(
      /manufacturer figure for a comparable BMG LABTECH CLARIOstar Plus/,
    ),
  ).toBeVisible();
  await expect(
    reader.getByText(
      /At the front, left, 0\.07 m above the bench; its drawer comes out 0\.18 m/,
    ),
  ).toBeVisible();
  await reader.getByText("Sources").click();
  await expect(reader.getByText(/manufacturer_dimensions_m/)).toBeVisible();
  // A comparable model's figures, never the cloud lab's own specification.
  await expect(
    reader.getByText(/not this instrument's specification/),
  ).toBeVisible();
  await section.getByRole("button", { name: /500 MHz NMR/ }).click();
  await expect(
    page.getByText("No 3D model; the twin is one estimated box."),
  ).toBeVisible();
  await expect(page.getByText(/models 96 of the 480 tubes/)).toBeVisible();
});
