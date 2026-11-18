import { expect, test } from "@playwright/test";

test("without a record key the record step says so instead of offering a record", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  // A deployment with no signing key answers 503, as AWS does until one is configured.
  await page.route("**/api/cloudlab/qualifications/me", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        detail:
          "Training records cannot be signed here: no record key is configured",
      }),
    }),
  );
  await page.goto("/#/cloudlab");
  await page.getByRole("button", { name: "Start training" }).click();
  await page.getByRole("button", { name: /Record$/ }).click();
  await expect(
    page.getByText("This deployment cannot sign training records yet"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Attach to a run request" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Download record" }),
  ).toBeDisabled();
});
