import { expect, test } from "@playwright/test";

test("the start page maps every stop on both routes to its page", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Roadmap learner");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();

  const learning = page.getByRole("region", { name: "Learning route" });
  const using = page.getByRole("region", { name: "Using route" });
  await expect(learning.getByRole("listitem")).toHaveCount(5);
  await expect(using.getByRole("listitem")).toHaveCount(5);

  const start = page.getByRole("button", { name: "Start here", exact: true });

  // Starting the route opens its first stop, the same page as stop 1.
  await learning.getByRole("button", { name: "Start the route" }).click();
  await expect(page).toHaveURL(/#\/instruments$/);
  await start.click();
  const stops: [typeof learning, string, RegExp, string][] = [
    [
      learning,
      "Meet the instruments",
      /#\/instruments$/,
      "What the robot is made of",
    ],
    [learning, "Learning lab", /#\/learn$/, "Learning lab"],
    [learning, "Simulation lab", /#\/sim$/, "Four sources. One mixture."],
    [
      learning,
      "Workflow marketplace",
      /#\/marketplace$/,
      "Workflow marketplace",
    ],
    [learning, "Study groups", /#\/groups$/, "Study groups"],
    [using, "Add a device", /#\/onboard$/, "Add a device"],
    [using, "Teaching twin", /#\/twin$/, "Teaching twin"],
    [using, "Plan a workcell", /#\/plan$/, "Plan a workcell"],
    [using, "Real-device readiness", /#\/readiness$/, "Real-device readiness"],
    [using, "Teaching runs", /#\/runs$/, "Teaching runs"],
  ];
  for (const [route, name, url, heading] of stops) {
    await route.getByRole("button", { name }).click();
    await expect(page).toHaveURL(url);
    await expect(
      page.getByRole("heading", { name: heading, exact: true }),
    ).toBeVisible();
    await start.click();
  }

  // A learning page's back link returns to the map it was opened from.
  await learning.getByRole("button", { name: "Simulation lab" }).click();
  await page
    .getByRole("button", { name: "Back to start", exact: true })
    .click();
  await expect(learning).toBeVisible();
  await expect(page).toHaveURL(/\/$/);
});
