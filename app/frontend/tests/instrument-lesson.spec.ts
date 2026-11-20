import { expect, test } from "@playwright/test";

test("each cloud lab instrument opens its own studio", async ({ page }) => {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.goto("/#/instruments");

  const section = page.getByRole("region", { name: "In a cloud lab" });
  await section.getByRole("button", { name: /Plate washer/ }).click();
  await page
    .getByRole("article", { name: "Plate washer" })
    .getByRole("button", { name: "Use it" })
    .click();
  await expect(page).toHaveURL(/#\/instruments\/plate-washer$/);
  // The studio is the instrument's, not the multi-instrument workflow.
  await expect(
    page.getByRole("heading", { level: 1, name: "Plate washer." }),
  ).toBeVisible();
  await expect(page.getByText(/Empties wells and refills them/)).toBeVisible();

  // It starts with every action the twin has, once, and every step fits.
  const steps = page.getByRole("region", { name: "Steps" });
  await expect(steps.getByTestId(/instrument-step-/)).toHaveCount(3);
  await expect(page.getByTestId("instrument-step-1")).toContainText("Load");
  await expect(steps.getByText("Every step fits")).toBeVisible();
  const add = steps.getByRole("group", { name: "Add a step" });
  await expect(add.getByRole("button")).toHaveText(["Load", "Mix", "Wait"]);

  // A step the twin cannot take says why, beside the step.
  await page.getByRole("button", { name: "Delete step 1" }).click();
  await expect(steps.getByText("Step 1 breaks a rule")).toBeVisible();
  await expect(page.getByTestId("instrument-step-1")).toContainText(
    "load plate first",
  );
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Start again" }).click();
  await expect(steps.getByText("Every step fits")).toBeVisible();

  // Running steps through the twin moves the model to what each step does.
  const run = page.getByRole("region", {
    name: "Teaching simulation controls",
  });
  await run.getByRole("button", { name: "Advance one step" }).click();
  await expect(run).toContainText("1 / 3");
  await expect(page.getByTestId("instrument-step-1")).toHaveAttribute(
    "aria-current",
    "step",
  );
  const states = page
    .getByRole("region", { name: "Instrument" })
    .getByRole("group", { name: "State" });
  await expect(
    states.getByRole("button", { name: "Plate in" }),
  ).toHaveAttribute("aria-pressed", "true");
  await run.getByRole("button", { name: "Advance one step" }).click();
  await expect(states.getByRole("button", { name: "Washing" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await run.getByRole("button", { name: "Run teaching simulation" }).click();
  await expect(run).toContainText("Run finished.");
  await expect(run).toContainText("3 / 3");
  if (process.env.SHOTS)
    await page.screenshot({
      path: `${process.env.SHOTS}/instrument-studio.png`,
    });

  // Its anatomy numbers the parts inside; picking one says what it does.
  const inside = page.getByRole("region", { name: "Anatomy" });
  const key = inside.getByRole("listitem");
  await expect(key).toHaveCount(6);
  await expect(key.first()).toContainText("1Manifold");
  await key.first().getByRole("button").click();
  await expect(key.first().getByRole("button")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(inside).toContainText(
    "Manifold. Rows of tubes that dispense buffer into the wells and aspirate it again.",
  );
  await expect(
    inside.getByRole("slider", { name: "Take apart" }),
  ).toBeVisible();

  await page.getByText("About this instrument").click();
  await expect(
    page.getByText("96-tube manifold for 96-well SBS plates"),
  ).toBeVisible();
  await expect(page.getByText(/MBZUAI, CC-BY-NC-4\.0/)).toBeVisible();
  await expect(
    page.getByText("16.5 kg · manufacturer figure for a comparable"),
  ).toBeVisible();
  await expect(
    page.getByText(/not this instrument's specification/),
  ).toBeVisible();

  // Chaining instruments is the next page, not this one.
  await page
    .getByRole("button", { name: /Chain it with other instruments/ })
    .click();
  await expect(page).toHaveURL(/#\/cloudlab-workflow$/);
  await page.goBack();
  await expect(
    page.getByRole("heading", { level: 1, name: "Plate washer." }),
  ).toBeVisible();

  // An estimated box is practised the same way, without a model.
  await page.goto("/#/instruments/nmr");
  await expect(
    page.getByRole("heading", { level: 1, name: "500 MHz NMR spectrometer." }),
  ).toBeVisible();
  await expect(
    page.getByText("No 3D model; the twin is one estimated box."),
  ).toBeVisible();
  await expect(page.getByRole("region", { name: "Anatomy" })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /Chain it with other instruments/ }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: /Next instrument/ }).click();
  await expect(page).toHaveURL(/#\/instruments\/dls-plate-reader$/);
  await page
    .getByRole("button", { name: "Meet the instruments" })
    .last()
    .click();
  await expect(
    page.getByRole("region", { name: "In a cloud lab" }),
  ).toBeVisible();
});
