import { expect, test } from "@playwright/test";

test("a published workflow is drawn as a workcell the sample travels through", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await page.getByRole("button", { name: "Learning lab", exact: true }).click();
  await page.getByRole("link", { name: /Intermediate/ }).click();

  const cells = page.getByRole("region", {
    name: "Published workflows as workcells",
  });
  // Each station is a twin that can do the step, coloured by the part it takes.
  const stations = cells.getByRole("list", { name: "Stations" });
  await expect(stations.getByRole("button")).toHaveCount(3);
  await expect(
    cells.getByRole("img", { name: /Find a better electrolyte as a workcell/ }),
  ).toBeVisible();
  await expect(stations.getByRole("button").last()).toHaveAttribute(
    "data-stage",
    "test",
  );

  // The sample goes from the first station to the last.
  await cells.getByRole("button", { name: "Follow the sample" }).click();
  await expect(
    cells.getByText("Measure ionic conductivity").first(),
  ).toBeVisible();
  await expect(stations.getByRole("button").last()).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  // Another paper is another workcell.
  await cells
    .getByRole("button", { name: /When pipetting is not the answer/ })
    .click();
  await expect(stations.getByRole("button")).toHaveCount(4);
  await expect(stations).toContainText("Powder X-ray diffractometer");
  await expect(stations.getByRole("button").last()).toHaveAttribute(
    "data-stage",
    "characterize",
  );
  expect(errors).toEqual([]);
});
