import { expect, test, type Browser, type Page } from "@playwright/test";

async function learner(browser: Browser, name: string) {
  const page = await (await browser.newContext()).newPage();
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill(name);
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  return page;
}

async function ranWorkflow(page: Page, title: string) {
  let session = await (
    await page.request.post("/api/sessions", { data: { title } })
  ).json();
  const path = `/api/sessions/${session.id}`;
  session = await (
    await page.request.post(`${path}/start`, {
      data: { version: session.version },
    })
  ).json();
  while (session.status === "running")
    session = await (
      await page.request.post(`${path}/advance`, {
        data: { version: session.version },
      })
    ).json();
  return session;
}

async function openReviews(page: Page) {
  await page.reload();
  await page.getByRole("button", { name: "Reviews", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Reviews", level: 1 }),
  ).toBeVisible();
}

test("a facilitator pins a comment to a step and the learner replies and resolves it", async ({
  browser,
}) => {
  const ada = await learner(browser, "Ada");
  const grace = await learner(browser, "Grace");
  const mallory = await learner(browser, "Mallory");
  const group = await (
    await ada.request.post("/api/groups", { data: { name: "Review circle" } })
  ).json();
  expect(
    (
      await grace.request.post("/api/groups/join", {
        data: { code: group.code },
      })
    ).ok(),
  ).toBe(true);
  await ranWorkflow(grace, "Grace's dilution");

  await openReviews(grace);
  await grace.getByRole("button", { name: "Ask for review" }).click();
  await expect(
    grace.getByRole("heading", { name: "Grace's dilution", level: 1 }),
  ).toBeVisible();
  await expect(grace.getByText("Synthetic replay")).toBeVisible();

  await openReviews(ada);
  await ada
    .getByRole("button", { name: /Grace's dilution.*Grace · Workflow run/ })
    .click();
  const steps = ada.getByRole("list", { name: "Steps" });
  await steps.getByRole("button").nth(1).click();
  await ada
    .getByLabel("Comment on step 2")
    .fill("Why a fresh aspiration here?");
  await ada.getByRole("button", { name: "Comment", exact: true }).click();
  await expect(ada.getByText("Why a fresh aspiration here?")).toBeVisible();

  // Someone outside the group learns nothing about the review.
  const reviews = await (await ada.request.get("/api/reviews")).json();
  const item = reviews.to_review[0];
  const outside = await mallory.request.get(
    `/api/reviews/groups/${item.group_id}/items/${item.id}`,
  );
  expect(outside.status()).toBe(404);

  await openReviews(grace);
  await grace.getByRole("button", { name: /1 open comment/ }).click();
  await grace
    .getByRole("list", { name: "Steps" })
    .getByRole("button")
    .nth(1)
    .click();
  await expect(grace.getByText("Why a fresh aspiration here?")).toBeVisible();
  await grace
    .getByRole("textbox", { name: "Reply to Ada" })
    .fill("The tip only holds one load.");
  await grace.getByRole("button", { name: "Reply" }).click();
  await expect(grace.getByText("The tip only holds one load.")).toBeVisible();
  await grace.getByRole("button", { name: "Resolve" }).click();
  await expect(grace.getByText("Resolved by Grace")).toBeVisible();

  // The replay stays within a phone's width.
  await grace.setViewportSize({ width: 390, height: 844 });
  const overflow = await grace.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

test("a classmate reviews what a facilitator shared, as in the first feedback", async ({
  browser,
}) => {
  const sonia = await learner(browser, "Sonia");
  const sarah = await learner(browser, "Sarah");
  const group = await (
    await sonia.request.post("/api/groups", { data: { name: "Mixtures co." } })
  ).json();
  await sarah.request.post("/api/groups/join", { data: { code: group.code } });
  await ranWorkflow(sonia, "Sonia's transfer");

  await openReviews(sonia);
  await sonia.getByRole("button", { name: "Ask for review" }).click();
  await expect(
    sonia.getByRole("heading", { name: "Sonia's transfer", level: 1 }),
  ).toBeVisible();

  // Sarah is a member, not the facilitator, and still gets the request to review.
  await openReviews(sarah);
  const queue = sarah.getByRole("region", { name: "To review" });
  await queue
    .getByRole("button", { name: /Sonia's transfer.*Sonia · Workflow run/ })
    .click();
  await sarah
    .getByRole("list", { name: "Steps" })
    .getByRole("button")
    .nth(1)
    .click();
  await sarah.getByLabel("Comment on step 2").fill("Same tip as mine?");
  await sarah.getByRole("button", { name: "Comment", exact: true }).click();
  await expect(sarah.getByText("Same tip as mine?")).toBeVisible();
  // She resolves her own thread.
  await sarah.getByRole("button", { name: "Resolve" }).click();
  await expect(sarah.getByText("Resolved by Sarah")).toBeVisible();
});
