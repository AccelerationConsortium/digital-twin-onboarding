import { expect, test } from "@playwright/test";

test("the browser's back and forward buttons step through visited pages", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "This is my first time" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();

  const sidebar = page.locator("nav");
  await sidebar.getByRole("button", { name: /Learning lab/ }).click();
  await expect(
    page.getByRole("heading", { name: "Learning lab" }),
  ).toBeVisible();
  await sidebar.getByRole("button", { name: "Study groups" }).click();
  await expect(
    page.getByRole("heading", { name: "Study groups" }),
  ).toBeVisible();
  await sidebar.getByRole("button", { name: "Add a device" }).first().click();
  await expect(
    page.getByRole("heading", { name: "Add a device" }),
  ).toBeVisible();

  await page.goBack();
  await expect(page).toHaveURL(/#\/groups$/);
  await expect(
    page.getByRole("heading", { name: "Study groups" }),
  ).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/#\/learn/);
  await expect(
    page.getByRole("heading", { name: "Learning lab" }),
  ).toBeVisible();
  await page.goForward();
  await expect(page).toHaveURL(/#\/groups$/);
  await expect(
    page.getByRole("heading", { name: "Study groups" }),
  ).toBeVisible();
});
