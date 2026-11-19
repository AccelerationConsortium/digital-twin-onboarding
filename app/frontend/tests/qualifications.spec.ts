import { expect, test, type Page } from "@playwright/test";

async function enter(page: Page) {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
}

const WARM_READ = [
  ["load", { device: "incubator", volume_ul: 200 }],
  ["heat", { device: "incubator", celsius: 37 }],
  ["transfer", { arm: "arm", source: "incubator", target: "reader" }],
  ["read", { device: "reader" }],
] as const;
const TOO_HOT = [
  ["load", { device: "incubator", volume_ul: 200 }],
  ["heat", { device: "incubator", celsius: 80 }],
  ["request_operator", { reason: "80 °C is above the incubator's limit" }],
] as const;

/** One sandbox episode run through the agent API, for a named agent or the person. */
async function episode(
  page: Page,
  scenario: string,
  calls: readonly (readonly [string, object])[],
  agent?: string,
) {
  const base = "/api/node/v1/sandbox/episodes";
  const { version } = await (await page.request.get(base)).json();
  const opened = await (
    await page.request.post(base, {
      data: { expected_version: version, scenario, ...(agent && { agent }) },
    })
  ).json();
  let current = opened.version;
  for (const [tool, args] of calls) {
    const response = await page.request.post(
      `${base}/${opened.episode.id}/calls`,
      { data: { expected_version: current, tool, args } },
    );
    expect(response.ok()).toBe(true);
    current = (await response.json()).version;
  }
}

test("a person and an agent see what each qualification still needs, then issue and verify one", async ({
  page,
}) => {
  await enter(page);
  await episode(page, "warm-read", WARM_READ, "planner-2");
  await episode(page, "too-hot", TOO_HOT, "planner-2");
  await episode(page, "warm-read", WARM_READ);

  await page.getByRole("button", { name: "Qualifications" }).click();
  await expect(
    page.getByRole("heading", { name: "Qualifications", level: 1 }),
  ).toBeVisible();
  await expect(page.getByText("Synthetic evidence")).toBeVisible();

  // The person comes first; their missing criteria point at the pages that train them.
  const sections = page.locator("main section[aria-label]");
  await expect(sections.first()).toHaveAttribute("aria-label", "You");
  const you = page.getByRole("region", { name: "You" });
  const yourIncubator = you.getByRole("article", { name: "Incubator" });
  await expect(
    yourIncubator.locator("li[data-passed=true]", {
      hasText: "Runs a workflow on the twin to its goal",
    }),
  ).toContainText("Agent sandbox");
  await expect(
    yourIncubator.getByRole("link", { name: "Fault drills checkride" }),
  ).toBeVisible();
  await expect(
    you
      .getByRole("article", { name: "Liquid handler" })
      .getByRole("link", { name: "Cloud lab training" })
      .first(),
  ).toBeVisible();
  await expect(
    you.getByRole("button", { name: "Issue signed record" }),
  ).toHaveCount(0);

  // The agent's passes are its own; only the sandbox trains it.
  const agent = page.getByRole("region", { name: "Agent · planner-2" });
  const agentIncubator = agent.getByRole("article", { name: "Incubator" });
  await expect(agentIncubator).toHaveAttribute("data-complete", "true");
  await expect(agent.getByRole("link")).toHaveCount(0);

  // Another tab issues first, so this page's version is stale: it reloads and says why.
  const { version } = await (
    await page.request.get("/api/qualifications")
  ).json();
  expect(
    (
      await page.request.post("/api/qualifications/records", {
        data: {
          expected_version: version,
          instrument: "incubator",
          agent: "planner-2",
        },
      })
    ).ok(),
  ).toBe(true);
  await agentIncubator
    .getByRole("button", { name: "Issue signed record" })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "changed in another request",
  );
  await agentIncubator
    .getByRole("button", { name: "Issue signed record" })
    .click();
  const issued = page.getByRole("region", { name: "Issued qualification" });
  await expect(issued).toContainText("Incubator · Agent · planner-2");
  await expect(issued).toContainText(
    "It does not authorize use of any instrument",
  );
  await expect(page.getByRole("alert")).toHaveCount(0);

  const download = page.waitForEvent("download");
  await issued.getByRole("button", { name: "Download JSON" }).click();
  expect((await download).suggestedFilename()).toBe(
    "academy-qualification-incubator.json",
  );

  // The verify box starts with the record just issued.
  const verify = page.getByRole("form", { name: "Verify a qualification" });
  await verify.getByLabel("Cleared for").selectOption("incubator");
  await verify.getByLabel("Held by").selectOption("agent");
  await verify.getByRole("button", { name: "Verify" }).click();
  const verdict = verify.getByRole("status", { name: "Verification" });
  await expect(verdict).toContainText("Authentic");
  await expect(verdict).toContainText("Valid until");
  await expect(verdict).toContainText("Cleared for incubator, an agent");

  await verify.getByLabel("Cleared for").selectOption("plate-reader");
  await verify.getByRole("button", { name: "Verify" }).click();
  await expect(verdict).toContainText("Not cleared");
  await expect(verdict).toContainText("for incubator, not plate-reader");

  const envelope = JSON.parse(
    await verify.getByLabel("Signed record").inputValue(),
  );
  const payload: string = envelope.payload;
  envelope.payload =
    payload.slice(0, 20) +
    (payload[20] === "A" ? "B" : "A") +
    payload.slice(21);
  await verify.getByLabel("Signed record").fill(JSON.stringify(envelope));
  await verify.getByRole("button", { name: "Verify" }).click();
  await expect(verdict).toContainText("Not authentic");

  await verify.getByLabel("Signed record").fill("not a record");
  await verify.getByRole("button", { name: "Verify" }).click();
  await expect(verify.getByRole("alert")).toContainText("Paste the record");

  // A missing criterion's link opens the page that trains it.
  await yourIncubator
    .getByRole("link", { name: "Fault drills checkride" })
    .click();
  await expect(page).toHaveURL(/#\/drills$/);
  await expect(
    page.getByRole("heading", { name: "Fault drills", level: 1 }),
  ).toBeVisible();
});

test("the qualifications page fits a phone", async ({ page }) => {
  await enter(page);
  await episode(page, "warm-read", WARM_READ, "planner-2");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/qualifications");
  await expect(
    page.getByRole("heading", { name: "Qualifications", level: 1 }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Agent · planner-2" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
