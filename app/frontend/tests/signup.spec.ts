import { test, expect } from "@playwright/test";

for (const domains of [["utoronto.ca", "mail.utoronto.ca"], []]) {
  test(`Cognito welcome explains ${domains.length ? "university and student registration" : "invited access"}`, async ({
    page,
  }) => {
    await page.route("**/api/config", async (route) => {
      const response = await route.fetch();
      await route.fulfill({
        response,
        json: {
          ...(await response.json()),
          auth: "cognito",
          issuer: "https://cognito-idp.ca-central-1.amazonaws.com/test-pool",
          client_id: "test-client",
          cognito_domain: "https://test.auth.ca-central-1.amazoncognito.com",
          self_signup_email_domains: domains,
        },
      });
    });
    await page.goto("/");
    await expect(page.getByPlaceholder("Your first name")).toHaveCount(0);
    if (domains.length) {
      await expect(
        page.getByRole("button", { name: "Sign in or create an account" }),
      ).toBeEnabled();
      await expect(
        page.getByText(
          "New learners can sign up with @utoronto.ca or @mail.utoronto.ca. Verify your email to start learning.",
        ),
      ).toBeVisible();
    } else {
      await expect(
        page.getByRole("button", { name: "Sign in to Lab Onboarding" }),
      ).toBeEnabled();
      await expect(
        page.getByText("Use your training account to save your progress."),
      ).toBeVisible();
    }

    // Any other email asks a lab operator; nothing is granted by asking.
    await page
      .getByRole("button", { name: "Request access with another email" })
      .click();
    await expect(
      page.getByRole("heading", { name: "Request access" }),
    ).toBeVisible();
    await page
      .getByLabel("Email")
      .fill(`guest-${domains.length}-${Date.now()}@example.com`);
    await page.getByLabel("Name", { exact: true }).fill("Grace");
    await page.getByLabel("Lab or course (optional)").fill("Visiting lab");
    await page.getByRole("button", { name: "Send request" }).click();
    await expect(page.getByRole("status")).toContainText("Request sent.");
    await page.getByRole("button", { name: "Back to sign in" }).click();
    await expect(page.getByRole("button", { name: /^Sign in/ })).toHaveCount(2);
  });
}
