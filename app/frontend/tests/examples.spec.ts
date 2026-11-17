import { expect, test } from "@playwright/test";

test("an example workcell opens with a layout the arm can run", async ({
  page,
}) => {
  test.setTimeout(120_000);
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

  const examples = page.getByRole("region", { name: "Example workcells" });
  await expect(examples.getByRole("listitem")).toHaveCount(8);
  // The hand-set synthesis workcell is listed with the planned examples.
  await expect(
    examples.getByRole("link", { name: /Synthesis workcell/ }),
  ).toHaveAttribute("href", "#/onboard/case-synthesis-cell");
  await examples
    .getByRole("button", { name: /Flex, plate sealer, plate reader/ })
    .click();

  // It lands on the layout, with both transfers planned and simulated.
  // Opening plans and simulates both transfers first, which a busy runner takes a while over.
  await expect(page.getByRole("tab", { name: "4 · Layout" })).toHaveAttribute(
    "aria-selected",
    "true",
    { timeout: 60_000 },
  );
  const paths = page.getByRole("button", { name: /^Step \d+ · / });
  // Two transfers are planned and simulated, which a busy runner takes a while over.
  await expect(paths).toHaveCount(2, { timeout: 60_000 });
  await expect(paths.first()).toContainText("cm min clearance");
  await expect(
    page.getByRole("button", { name: "Save layout" }),
  ).toBeDisabled();

  // The workflow is laid out in time, one lane per instrument, with the arm's joints,
  // a log of every step and where the sample is.
  const data = page.getByRole("region", { name: "Workflow timeline" });
  await expect(data.getByText(/^0\.0 \/ \d+\.\d s$/)).toBeVisible();
  const joints = data.getByRole("group", { name: "Arm joints" });
  await expect(joints.getByRole("meter")).toHaveCount(6);
  await expect(joints.getByText("Waiting")).toBeVisible();
  await expect(
    data.getByRole("list", { name: "Run log" }).getByRole("listitem"),
  ).toHaveCount(6);
  await expect(data.getByText("No sample loaded yet.")).toBeVisible();
  // Choosing a transfer plays it: the arm is doing something and carries the sample.
  await paths.first().click();
  await expect(
    joints.getByText(/Lower into|Lift from|Transit to/),
  ).toBeVisible();
  await expect(data.getByText("carried by UR5e arm")).toBeVisible();
  await expect(joints.getByText(/\d+\.\d cm to /)).toBeVisible();
  await data.getByRole("button", { name: "Pause workflow" }).click();
  // Dragging to the end leaves the sample where the workflow puts it.
  await data.getByLabel("Workflow time").press("End");
  await expect(
    data.getByRole("cell", { name: /^Plate reader \(CLARIOstar Plus\)/ }),
  ).toBeVisible();
  await page.screenshot({
    path: "/tmp/academy-layout-data.png",
    fullPage: true,
  });
  // No language model is configured here, so layout requests are not offered.
  await expect(page.getByLabel("Change this layout")).toHaveCount(0);

  // Opening another example asks before replacing the first.
  await page.getByRole("tab", { name: "1 · Describe" }).click();
  page.once("dialog", (dialog) => dialog.dismiss());
  await examples.getByRole("button", { name: /OT-2 to Flex/ }).click();
  await page.getByRole("tab", { name: "2 · Instruments" }).click();
  await expect(page.getByText("Plate sealer (a4S)").first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("a layout request in plain words lands on the draft for review", async ({
  page,
}) => {
  test.setTimeout(120_000);
  // This server has no language model: the catalog says it has one and its answer is canned.
  let asked = "";
  await page.route("**/api/twins/layout/refine", async (route) => {
    const sent = route.request().postDataJSON();
    asked = sent.text;
    const reader = sent.placements[2];
    await route.fulfill({
      json: {
        bench: sent.bench,
        placements: sent.placements.map((p: { twin_id: string; x: number }) =>
          p.twin_id === reader.twin_id
            ? { ...p, x: Number((p.x - 0.05).toFixed(2)), kept: true }
            : p,
        ),
        constraints: [{ kind: "zone", twin_id: reader.twin_id, side: "left" }],
        applied: [
          "Plate reader (CLARIOstar Plus) moved 0.05 m toward the left",
          "Plate reader (CLARIOstar Plus) on the left",
        ],
        skipped: ["Centrifuge"],
        unclear: "",
        search: true,
        model: "Amazon Nova Pro",
      },
    });
  });
  await page.route(/\/api\/twins(\/.*)?$/, async (route) => {
    if (route.request().url().endsWith("/layout/refine"))
      return route.fallback();
    // A check still in flight when the test ends has nobody left to answer.
    const response = await route.fetch().catch(() => null);
    if (!response) return;
    const body = await response.json().catch(() => null);
    if (!response.ok() || !Array.isArray(body?.twins))
      return route.fulfill({ response });
    await route.fulfill({
      response,
      json: { ...body, refine_available: true },
    });
  });
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
  const path = page.getByRole("button", { name: /^Step 3 · / });
  await expect(path).toContainText("cm min clearance", { timeout: 60_000 });

  const request = page.getByLabel("Change this layout");
  const refine = page.getByRole("button", { name: "Refine" });
  await expect(refine).toBeDisabled();
  await request.fill("Move the reader 5 cm left and put the centrifuge away");
  await refine.click();
  await expect(
    page.getByText(
      "Plate reader (CLARIOstar Plus) moved 0.05 m toward the left",
    ),
  ).toBeVisible();
  await expect(page.getByText("Not applied: Centrifuge")).toBeVisible();
  expect(asked).toBe("Move the reader 5 cm left and put the centrifuge away");
  // The change is on the draft: checked again, and waiting to be saved.
  await expect(path).toContainText("cm min clearance");
  await expect(page.getByRole("button", { name: "Save layout" })).toBeEnabled();
  await expect(request).toHaveValue("");
  // A preference is the learner's to keep: it is saved only when they say so.
  await page.getByRole("button", { name: "Save these preferences" }).click();
  await expect(
    page.getByText("Search layouts to place the instruments this way."),
  ).toBeVisible();
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

test("a planned arm path opens as waypoints to edit and check by hand", async ({
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
    .getByRole("button", { name: /Flex to plate reader/ })
    .click();
  await page
    .getByRole("button", { name: "Edit the arm path of step 3" })
    .click({ timeout: 60_000 });

  const editor = page.getByRole("region", { name: "Arm path editor" });
  await expect(editor.getByRole("heading")).toContainText(
    /Arm path · step 3 · \d+\/24 waypoints/,
    { timeout: 60_000 },
  );
  const points = editor.getByRole("list", { name: "Waypoints" });
  const planned = await points.getByRole("listitem").count();
  expect(planned).toBeGreaterThan(1);
  // The timeline steps aside while a path is edited.
  await expect(
    page.getByRole("region", { name: "Workflow timeline" }),
  ).toHaveCount(0);

  // The planned waypoints pass their own check.
  const check = editor.getByRole("button", { name: "Check path" });
  await check.click();
  const verdict = editor.getByRole("status");
  await expect(verdict).toContainText(
    "This path is clear and reaches both instruments.",
    { timeout: 60_000 },
  );
  await expect(verdict).toContainText(/\d+% joint torque/);
  await expect(
    editor.getByRole("button", { name: "Edited chain" }),
  ).toBeVisible();

  // Folding the elbow at the first waypoint is an edit: the verdict goes, and the
  // next check says what the arm would hit.
  await editor.getByLabel("J2 Shoulder degrees").fill("0");
  await editor.getByLabel("J3 Elbow degrees").fill("150");
  await expect(verdict).toHaveCount(0);
  await check.click();
  await expect(verdict).toContainText("would hit", { timeout: 60_000 });
  await expect(
    editor.getByRole("button", { name: "Edited chain" }),
  ).toHaveCount(0);

  // Waypoints can be added and removed, and the plan brought back.
  await editor.getByRole("button", { name: "Add after" }).click();
  await expect(points.getByRole("listitem")).toHaveCount(planned + 1);
  await editor.getByRole("button", { name: "Delete waypoint 2" }).click();
  await expect(points.getByRole("listitem")).toHaveCount(planned);
  await editor.getByRole("button", { name: "Back to planned" }).click();
  await check.click();
  await expect(verdict).toContainText("This path is clear", {
    timeout: 60_000,
  });
  await page.screenshot({
    path: "/tmp/academy-chain-editor.png",
    fullPage: true,
  });

  await editor
    .getByRole("button", { name: "Close the arm path editor" })
    .click();
  await expect(
    page.getByRole("region", { name: "Workflow timeline" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("a found layout is improved toward the chosen objectives", async ({
  page,
}) => {
  test.setTimeout(240_000);
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

  await page.getByRole("button", { name: "Search layouts" }).click();
  const first = page.getByRole("button", { name: /^Layout \d+/ }).first();
  await expect(first).toContainText("m path", { timeout: 60_000 });
  await page.getByRole("button", { name: "Stop" }).click();
  // One plate goes through the workflow, so nothing overlaps and no parallel time is shown.
  await expect(first).not.toContainText("in parallel");

  // Shortest arm path and run time together.
  const objectives = page.getByRole("group", { name: "Optimise for" });
  await objectives.getByRole("button", { name: "Arm path" }).click();
  // Layouts beaten on both are hidden, so the best one left is the one to improve.
  const best = page.getByRole("button", { name: /^Layout \d+/ }).first();
  await best.click();
  const text = (await best.textContent())!;
  const n = (await best.locator("span").first().textContent())!.match(
    /^Layout (\d+)/,
  )![1];
  const before = Number(text.match(/([\d.]+) m path/)![1]);
  await page.getByRole("button", { name: `Improve layout ${n}` }).click();
  const improved = page.getByRole("button", {
    name: new RegExp(`^Layout \\d+ · improved from ${n}`),
  });
  await expect(improved).toBeVisible({ timeout: 180_000 });
  await expect(improved).toHaveAttribute("aria-pressed", "true");
  const after = Number(
    (await improved.textContent())!.match(/([\d.]+) m path/)![1],
  );
  expect(after).toBeLessThan(before);
  // The arm path of the improved layout is planned and shown.
  await expect(
    page.getByRole("button", { name: /^Step \d+ · / }).first(),
  ).toContainText("cm min clearance", { timeout: 60_000 });
});
