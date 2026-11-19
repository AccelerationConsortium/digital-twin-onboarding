import { expect, test } from "@playwright/test";

test("the public welcome page leads to sign-in without the instrument stories", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { level: 1, name: "Welcome to Lab Onboarding." }),
  ).toBeVisible();
  await expect(page.getByTestId("instrument-stories")).toHaveCount(0);
  await expect(page.getByText(/Opentrons|OT-2|Flex/)).toHaveCount(0);
  await expect(page.getByText("TEACHING MODEL · SYNTHETIC")).toBeVisible();
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByPlaceholder("Your first name")).toBeFocused();
  expect(errors).toEqual([]);
});

test("the welcome page fits a small screen in both themes with reduced motion", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "dark" });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Enter the learning lab", exact: true }),
  ).toBeVisible();
  for (const colorScheme of ["dark", "light"] as const) {
    await page.emulateMedia({ colorScheme });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  }
  const animation = await page
    .locator("svg circle")
    .first()
    .evaluate((el) => getComputedStyle(el).animationName);
  expect(animation).toBe("none");
});
