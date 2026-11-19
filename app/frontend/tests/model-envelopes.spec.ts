import { expect, test } from "@playwright/test";

type Entry = {
  collection: string;
  id: string;
  size_m: [number, number, number];
  mesh: { kind: string; url?: string; up?: "y" | "z" };
};
type Checked = {
  id: string;
  missing?: string;
  drawn?: [number[], number[]];
  scale?: number[];
};

// Every library instrument with a 3D model, new ones included, is drawn exactly inside
// the planning envelope the server's collision boxes are measured in.
test("every drawn model fills its planning envelope and no more", async ({
  page,
}) => {
  test.setTimeout(240_000);
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Ada");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  const entries: Entry[] = [];
  for (let offset = 0; ; offset += 24) {
    const page_ = await (
      await page.request.get(`/api/twins/library/models?offset=${offset}`)
    ).json();
    entries.push(...page_.results);
    if (offset + 24 >= page_.total) break;
  }
  const models = entries.filter((e) => e.mesh.kind !== "ur5e");
  expect(models.length).toBeGreaterThan(200);

  const checked: Checked[] = await page.evaluate(async (models) => {
    const { drawnBox, fitted, instrumentModel } = await import(
      "/src/instrumentModels.ts" as string
    );
    const out: Checked[] = [];
    for (const e of models) {
      const [width, depth, height] = e.size_m;
      const spec = {
        parts: [
          {
            size: [width, height, depth],
            position: [0, height / 2, 0],
            color: "#ffffff",
          },
        ],
      };
      let template;
      try {
        template = await instrumentModel(e.mesh);
      } catch (error) {
        // Library files are fetched separately; one not on this machine is skipped.
        out.push({ id: e.id, missing: String(error) });
        continue;
      }
      const drawn = fitted(template, spec, e.mesh.up);
      const box = drawnBox(drawn);
      out.push({
        id: e.id,
        drawn: [box.min.toArray(), box.max.toArray()],
        scale: drawn.userData.scale,
      });
    }
    return out;
  }, models);

  const wrong: string[] = [];
  const byId = new Map(models.map((m) => [m.id, m]));
  for (const c of checked) {
    if (c.missing) continue;
    const [width, depth, height] = byId.get(c.id)!.size_m;
    const want = [
      [-width / 2, 0, -depth / 2],
      [width / 2, height, depth / 2],
    ];
    const off = Math.max(
      ...[0, 1].flatMap((i) =>
        [0, 1, 2].map((k) => Math.abs(c.drawn![i][k] - want[i][k])),
      ),
    );
    if (off > 0.002) wrong.push(`${c.id} is drawn ${off.toFixed(3)} m off`);
    // The catalogued size is the model's own: fitting it barely stretches it.
    const stretch = Math.max(...c.scale!.map((v) => Math.abs(v - 1)));
    if (stretch > 0.03)
      wrong.push(
        `${c.id} is stretched ${c.scale!.map((v) => v.toFixed(3)).join(" × ")} to fit its catalogued size`,
      );
  }
  expect(wrong).toEqual([]);
  // The procedural workcell models are always on hand.
  const present = checked.filter((c) => !c.missing).map((c) => c.id);
  expect(present).toEqual(
    expect.arrayContaining(["opentrons-ot2", "precision-balance"]),
  );
  test.info().annotations.push({
    type: "models",
    description: `${present.length} checked, ${checked.length - present.length} not on this machine`,
  });
});
