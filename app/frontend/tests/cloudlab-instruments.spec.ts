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
  await expect(section.getByRole("listitem")).toHaveCount(3);
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
    reader.getByText(/^At the front, left · ChemLab-Assets estimate/),
  ).toBeVisible();
  await expect(
    reader.getByText(/^0\.07 m above the bench · ChemLab-Assets estimate/),
  ).toBeVisible();
  await expect(
    reader.getByText(/^Comes out 0\.18 m · ChemLab-Assets estimate/),
  ).toBeVisible();
  await reader.getByText("Sources").click();
  await expect(reader.getByText(/manufacturer_dimensions_m/)).toBeVisible();
  // A comparable model's figures, never the cloud lab's own specification.
  await expect(
    reader.getByText(/not this instrument's specification/),
  ).toBeVisible();
  // Each value carries its own source: the washer's height is a manufacturer figure,
  // the face it loads from only an estimate.
  await section.getByRole("button", { name: "Transfers" }).click();
  await section.getByRole("button", { name: /Plate washer/ }).click();
  const washer = page.getByRole("article", { name: "Plate washer" });
  await expect(
    washer.getByText(/^From above · ChemLab-Assets estimate/),
  ).toBeVisible();
  await expect(
    washer.getByText(/^0\.08 m above the bench · manufacturer figure/),
  ).toBeVisible();
  await section.getByRole("button", { name: "Spectroscopy" }).click();
  await section.getByRole("button", { name: /500 MHz NMR/ }).click();
  await expect(
    page.getByText("No 3D model; the twin is one estimated box."),
  ).toBeVisible();
  await expect(page.getByText(/models 96 of the 480 tubes/)).toBeVisible();
});

test("a cloud lab twin shows its parts move", async ({ page }) => {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.goto("/#/instruments");

  const section = page.getByRole("region", { name: "In a cloud lab" });
  await section
    .getByRole("button", { name: /Workcell cell incubator/ })
    .click();
  const detail = page.getByRole("article", { name: "Workcell cell incubator" });
  const states = detail.getByRole("group", { name: "State" });
  await expect(states.getByRole("button", { name: "Closed" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(detail.getByText(/Both doors are shut/)).toBeVisible();
  // A state moves the stand-in's own doors and says what is happening.
  await states.getByRole("button", { name: "Glass door open" }).click();
  await expect(
    states.getByRole("button", { name: "Glass door open" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    detail.getByText(
      "Both doors open, so a plate can go onto the lowest shelf.",
    ),
  ).toBeVisible();
  if (process.env.SHOTS)
    await detail.screenshot({ path: `${process.env.SHOTS}/meet-twin.png` });

  // An instrument with no jointed model keeps the plain view.
  await section.getByRole("button", { name: /Analytical HPLC/ }).click();
  const hplc = page.getByRole("article", { name: "Analytical HPLC" });
  await expect(hplc.locator("canvas")).toBeVisible();
  await expect(hplc.getByRole("group", { name: "State" })).toHaveCount(0);
});
