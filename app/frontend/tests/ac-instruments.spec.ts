import { expect, test } from "@playwright/test";

test("AC self-driving lab instruments are met, used and taken apart like cloud lab ones", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.goto("/#/instruments");

  // The cloud lab keeps its own list; the AC's instruments have theirs.
  await expect(
    page.getByRole("region", { name: "In a cloud lab" }).getByRole("listitem"),
  ).toHaveCount(24);
  const section = page.getByRole("region", {
    name: "At the Acceleration Consortium",
  });
  await expect(section.getByRole("listitem")).toHaveCount(31);
  await section
    .getByRole("button", { name: "Plate readers and imaging" })
    .click();
  await expect(section.getByRole("listitem")).toHaveCount(5);
  await section
    .getByRole("button", { name: /Imaging plate reader \(Cytation 5\)/ })
    .click();
  const detail = page.getByRole("article", {
    name: "Imaging plate reader (Cytation 5)",
  });
  await expect(
    detail.getByText("What the equipment reference lists"),
  ).toBeVisible();
  await expect(detail.getByText("SDL2-EQ01, SDL4-EQ01")).toBeVisible();
  // No model of a Cytation 5 exists, so an imager no other instrument is drawn with
  // stands in, named as the comparable it is.
  await expect(
    detail
      .getByText(/comparable Thermo Fisher Scientific iBright FL1500/)
      .first(),
  ).toBeVisible();
  await expect(detail.locator("canvas")).toBeVisible();
  await expect(
    detail.getByRole("link", { name: "Documentation" }),
  ).toHaveAttribute("href", /biotekcytation5usermanual\.pdf$/);

  // Use it opens the instrument's own studio, as for a cloud lab instrument.
  await detail.getByRole("button", { name: "Use it" }).click();
  await expect(page).toHaveURL(/#\/instruments\/ac-cytation-5$/);
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Imaging plate reader (Cytation 5).",
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Acceleration Consortium · Plate readers and imaging"),
  ).toBeVisible();
  const steps = page.getByRole("region", { name: "Steps" });
  await expect(steps.getByText("Every step fits")).toBeVisible();
  const run = page.getByRole("region", {
    name: "Teaching simulation controls",
  });
  // On a loaded runner the studio may still be settling, so click until the run starts.
  await expect(async () => {
    await run.getByRole("button", { name: "Run teaching simulation" }).click();
    await expect(run).not.toContainText("Ready to run.", { timeout: 2_000 });
  }).toPass({ timeout: 30_000 });
  await expect(run).toContainText("Run finished.", { timeout: 30_000 });
  await expect(page.getByRole("region", { name: "Anatomy" })).toBeVisible();
  await page.getByText("About this instrument").click();
  await expect(
    page.getByText("Agilent BioTek Cytation 5 (SDL2-EQ01, SDL4-EQ01)."),
  ).toBeVisible();

  // An AC stand-in new to the dataset is taken apart part by part.
  await page.goto("/#/instruments/ac-evaporator");
  const inside = page.getByRole("region", { name: "Anatomy" });
  const key = inside.getByRole("listitem");
  await expect(key).toHaveCount(5);
  await expect(key.first()).toContainText("1Lid");
  await key.nth(1).getByRole("button").click();
  await expect(inside).toContainText(
    "Rotor. Spins the plates so the liquid stays in the wells as it boils off.",
  );
  await expect(
    page
      .getByRole("region", { name: "Instrument" })
      .getByRole("group", { name: "State" })
      .getByRole("button", { name: "Lid open" }),
  ).toBeVisible();

  // Next instrument stays in the AC's list.
  await page.getByRole("button", { name: /Next instrument/ }).click();
  await expect(page).toHaveURL(/#\/instruments\/ac-filtration$/);
});

test("an instrument no library model resembles is drawn as a sketch of its product photo", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.goto("/#/instruments/ac-tecan");
  await expect(
    page.getByRole("heading", { level: 1, name: "Liquid handler (Tecan)." }),
  ).toBeVisible();
  const instrument = page.getByRole("region", { name: "Instrument" });
  await expect(instrument.getByText("PHOTO SKETCH")).toBeVisible();
  await expect(instrument.locator("canvas")).toBeVisible();
  await expect(
    page.getByText("No 3D model; the twin is one estimated box."),
  ).toHaveCount(0);
  // It says the shape is read off a photo; the twin's size is still its datasheet's.
  await expect(
    page.getByText(
      /Shape sketched from a Tecan Fluent 480 product photo, not measured\./,
    ),
  ).toBeVisible();
  // A sketch has no parts catalogued to take apart.
  await expect(page.getByRole("region", { name: "Anatomy" })).toHaveCount(0);

  // A model with no joints still shows each step of a run that has something to show.
  const view = instrument.locator("[data-state]");
  await expect(view).not.toHaveAttribute("data-cue");
  const advance = page.getByRole("button", { name: "Advance one step" });
  await advance.click();
  await expect(view).toHaveAttribute("data-cue", "load");
  await advance.click();
  await expect(view).toHaveAttribute("data-cue", "mix");
  // Waiting has nothing to draw.
  await advance.click();
  await expect(view).not.toHaveAttribute("data-cue");
});
