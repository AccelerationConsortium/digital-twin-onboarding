import { expect, test, type Page } from "@playwright/test";

async function enter(page: Page, name: string) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill(name);
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
}

test("a lab operator approves a waiting request and invites by email", async ({
  page,
}) => {
  const requests = [
    {
      id: "a1",
      version: 1,
      email: "guest@example.com",
      name: "Grace",
      note: "Visiting lab",
      status: "pending",
      created_at: "2026-11-20T10:00:00+00:00",
    },
  ];
  const posted: string[] = [];
  await page.route("**/api/access", (route) =>
    route.fulfill({ json: { plan_layouts: true, admit_learners: true } }),
  );
  await page.route("**/api/access-requests", (route) =>
    route.fulfill({ json: requests }),
  );
  await page.route("**/api/access-requests/a1/approve", async (route) => {
    posted.push(route.request().postData() ?? "");
    requests[0] = { ...requests[0], status: "invited", version: 2 };
    await route.fulfill({ json: requests[0] });
  });
  await page.route("**/api/invitations", async (route) => {
    posted.push(route.request().postData() ?? "");
    requests.push({
      ...requests[0],
      id: "b2",
      email: "new@example.org",
      name: "",
      note: "",
    });
    await route.fulfill({ json: requests[1] });
  });

  await enter(page, "Op");
  await page.getByRole("button", { name: "Access requests" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Access requests" }),
  ).toBeVisible();
  await expect(page.getByText("Visiting lab")).toBeVisible();
  await page.getByRole("button", { name: "Approve guest@example.com" }).click();
  await expect(page.getByText("No one is waiting.")).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Resend invitation to guest@example.com",
    }),
  ).toBeVisible();
  expect(JSON.parse(posted[0])).toEqual({ expected_version: 1 });

  await page.getByLabel("Invite by email").fill("new@example.org");
  await page
    .getByRole("button", { name: "Send invitation", exact: true })
    .click();
  await expect(page.getByText("new@example.org")).toBeVisible();
  await expect(page.getByLabel("Invite by email")).toHaveValue("");
  expect(JSON.parse(posted[1])).toEqual({ email: "new@example.org" });
});

test("learners are not offered the access page", async ({ page }) => {
  await enter(page, "Ada");
  await expect(
    page.getByRole("button", { name: "Study groups" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Access requests" }),
  ).toHaveCount(0);
});
