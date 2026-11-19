import { useEffect, useId, useState, type CSSProperties } from "react";
import s from "./SketchTwin.module.css";

/*
 * Hand-drawn anatomy plates of lab instruments: oblique line sketches whose parts
 * lift apart and settle back, one instrument after another. Decorative only.
 */
type Point = [number, number];
type Part = {
  paths: string[];
  faint?: string[];
  accent?: string[];
  dots?: Point[];
  move: Point;
  callout?: { from: Point; to: Point; text: string };
};
type Plate = {
  name: string;
  parts: Part[];
  trace: { axes: string; line: string; labels: [Point, string][] };
  flows: string[];
};

const f = (n: number) => n.toFixed(1);
// Sketched edges run a little past their corners, as construction lines do.
function seg(a: Point, b: Point, over = 8) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = Math.hypot(dx, dy) || 1;
  const ux = (dx / len) * over;
  const uy = (dy / len) * over;
  return `M${f(a[0] - ux)} ${f(a[1] - uy)}L${f(b[0] + ux)} ${f(b[1] + uy)}`;
}
const poly = (points: Point[], over = 5) =>
  points.map((p, i) => seg(p, points[(i + 1) % points.length], over)).join("");
// An ellipse whose first axis lies at `rot` degrees.
function ellipse([cx, cy]: Point, rx: number, ry: number, rot = 0) {
  const r = (rot * Math.PI) / 180;
  const a: Point = [cx + rx * Math.cos(r), cy + rx * Math.sin(r)];
  const b: Point = [cx - rx * Math.cos(r), cy - rx * Math.sin(r)];
  return `M${f(a[0])} ${f(a[1])}A${rx} ${ry} ${rot} 1 0 ${f(b[0])} ${f(b[1])}A${rx} ${ry} ${rot} 1 0 ${f(a[0])} ${f(a[1])}`;
}
// The near half of a horizontal ellipse, for the base of an upright cylinder.
const frontArc = ([cx, cy]: Point, rx: number, ry: number) =>
  `M${f(cx - rx)} ${f(cy)}A${rx} ${ry} 0 0 0 ${f(cx + rx)} ${f(cy)}`;
function upright(base: Point, rx: number, ry: number, h: number) {
  const top: Point = [base[0], base[1] - h];
  return [
    frontArc(base, rx, ry),
    ellipse(top, rx, ry),
    seg([base[0] - rx, base[1]], [top[0] - rx, top[1]], 3),
    seg([base[0] + rx, base[1]], [top[0] + rx, top[1]], 3),
  ];
}
function trace(x0: number, y0: number, w: number, fn: (t: number) => number) {
  const points: string[] = [];
  for (let i = 0; i <= 120; i++) {
    const t = i / 120;
    points.push(`${f(x0 + t * w)} ${f(y0 - fn(t))}`);
  }
  return `M${points.join("L")}`;
}
const peak = (t: number, at: number, h: number, width: number) =>
  h * Math.exp(-((t - at) ** 2) / (2 * width * width));

/* HPLC: a module stack fed by solvent bottles. */
function hplc(): Plate {
  const OX = 250;
  const OY = 612;
  const W = 290;
  const D = 190;
  const P = (x: number, y: number, z: number): Point => [
    OX + x + z * 0.45,
    OY - y - z * 0.3,
  ];
  const box = (y0: number, h: number) => [
    poly([P(0, y0, 0), P(W, y0, 0), P(W, y0 + h, 0), P(0, y0 + h, 0)]),
    poly([P(0, y0 + h, 0), P(W, y0 + h, 0), P(W, y0 + h, D), P(0, y0 + h, D)]),
    poly([P(W, y0, 0), P(W, y0, D), P(W, y0 + h, D), P(W, y0 + h, 0)]),
  ];
  const rect = (x0: number, y0: number, x1: number, y1: number) =>
    poly([P(x0, y0, 0), P(x1, y0, 0), P(x1, y1, 0), P(x0, y1, 0)], 3);

  const pump = { y: 0, h: 92 };
  const sampler = { y: 92, h: 118 };
  const oven = { y: 210, h: 82 };
  const detector = { y: 292, h: 78 };
  const tray = { y: 370, h: 18 };

  const vials: Point[] = [];
  for (let i = 0; i < 9; i++) {
    const [x, y] = P(40 + i * 26, sampler.y + 40, 0);
    vials.push([x, y - Math.sin((i / 8) * Math.PI) * 18]);
  }
  const [cx0, cy] = P(50, oven.y + 40, 0);
  const [cx1] = P(240, oven.y + 40, 0);
  const bottles = [40, 108, 176, 244].map((x) => P(x, tray.y + tray.h, 96));
  const exit = P(W, pump.y + 60, D * 0.5);
  const tubes = bottles.map(([bx, by], i) => {
    const top = by - 102;
    const run = exit[0] + 26 + i * 8;
    return `M${f(bx)} ${f(top)}C${f(bx)} ${f(top - 46)} ${f(run)} ${f(top - 46)} ${f(run)} ${f(top + 10)}L${f(run)} ${f(exit[1] - i * 6)}L${f(exit[0])} ${f(exit[1] - i * 6)}`;
  });

  return {
    name: "HPLC",
    parts: [
      {
        paths: [
          ...box(pump.y, pump.h),
          ellipse(P(56, pump.y + 46, 0), 15, 15),
          ellipse(P(104, pump.y + 46, 0), 15, 15),
          rect(190, pump.y + 52, 266, pump.y + 74),
        ],
        dots: [P(274, pump.y + 20, 0)],
        move: [0, 0],
        callout: { from: P(56, pump.y + 46, 0), to: [70, 600], text: "PUMP" },
      },
      {
        paths: [
          ...box(sampler.y, sampler.h),
          rect(22, sampler.y + 18, W - 22, sampler.y + sampler.h - 18),
        ],
        faint: [seg(P(150, sampler.y + 100, 0), P(150, sampler.y + 62, 0), 0)],
        dots: vials,
        move: [0, -22],
        callout: {
          from: P(W - 22, sampler.y + 60, 0),
          to: [780, 470],
          text: "AUTOSAMPLER",
        },
      },
      {
        paths: [
          ...box(oven.y, oven.h),
          rect(22, oven.y + 14, W - 22, oven.y + oven.h - 14),
          ellipse([cx0, cy], 5, 11),
          ellipse([cx1, cy], 5, 11),
        ],
        accent: [
          seg([cx0, cy - 11], [cx1, cy - 11], 0),
          seg([cx0, cy + 11], [cx1, cy + 11], 0),
        ],
        move: [0, -46],
        callout: { from: [cx1, cy], to: [790, 340], text: "COLUMN OVEN" },
      },
      {
        paths: [
          ...box(detector.y, detector.h),
          rect(30, detector.y + 40, 120, detector.y + 62),
          ellipse(P(220, detector.y + 40, 0), 12, 12),
        ],
        faint: [seg(P(200, detector.y + 40, 0), P(150, detector.y + 40, 0), 0)],
        move: [0, -72],
        callout: {
          from: P(220, detector.y + 40, 0),
          to: [800, 230],
          text: "DETECTOR",
        },
      },
      {
        paths: [
          ...box(tray.y, tray.h),
          ...bottles.flatMap((b) => [
            ...upright(b, 22, 7, 84),
            ...upright([b[0], b[1] - 84], 8, 3, 18),
          ]),
        ],
        faint: tubes,
        accent: bottles.map(([x, y]) => frontArc([x, y - 34], 22, 7)),
        move: [0, -110],
        callout: {
          from: [bottles[0][0] - 22, bottles[0][1] - 50],
          to: [110, 150],
          text: "SOLVENTS",
        },
      },
    ],
    flows: tubes.slice(1, 3),
    trace: {
      axes: "M600 690L846 690M600 690L600 586",
      line: trace(
        604,
        688,
        236,
        (t) =>
          2 +
          peak(t, 0.18, 34, 0.018) +
          peak(t, 0.36, 82, 0.022) +
          peak(t, 0.47, 26, 0.016) +
          peak(t, 0.72, 58, 0.026),
      ),
      labels: [
        [[608, 582], "AU"],
        [[846, 706], "t"],
      ],
    },
  };
}

/* XPS: a UHV sphere with its source, analyser, load lock, manipulator and pump. */
function xps(): Plate {
  const C: Point = [420, 400];
  const R = 128;
  const dir = (a: number): Point => [
    Math.cos((a * Math.PI) / 180),
    -Math.sin((a * Math.PI) / 180),
  ];
  const at = (a: number, r: number): Point => [
    C[0] + dir(a)[0] * r,
    C[1] + dir(a)[1] * r,
  ];
  // A tube leaving the chamber along angle `a`, closed by a flange.
  function port(a: number, r0: number, length: number, w: number) {
    const [ux, uy] = dir(a);
    const vx = -uy * w;
    const vy = ux * w;
    const s0 = at(a, r0);
    const s1 = at(a, r0 + length);
    const rot = (Math.atan2(uy, ux) * 180) / Math.PI;
    return [
      seg([s0[0] + vx, s0[1] + vy], [s1[0] + vx, s1[1] + vy], 4),
      seg([s0[0] - vx, s0[1] - vy], [s1[0] - vx, s1[1] - vy], 4),
      ellipse(s1, w * 0.32, w, rot),
      ellipse(at(a, r0 + 8), w * 0.4, w * 1.3, rot),
    ];
  }
  const outward = (a: number, by: number): Point => [
    dir(a)[0] * by,
    dir(a)[1] * by,
  ];
  const rad = (d: number) => (d * Math.PI) / 180;

  const lensEnd = at(52, R + 92);
  const A: Point = [lensEnd[0] + 84, lensEnd[1] - 6];
  const shell = (r: number) =>
    `M${f(A[0] - r)} ${f(A[1])}A${r} ${r} 0 0 1 ${f(A[0] + r)} ${f(A[1])}`;
  const sourceEnd = at(158, R + 96);
  const lock = at(-12, R + 30);
  const rodBase = at(96, R + 34);
  const rod = at(96, R + 150);
  const pumpEnd = at(-90, R + 70);
  const turbo: Point = [pumpEnd[0], pumpEnd[1] + 44];
  const beamFrom = at(158, R - 10);

  return {
    name: "XPS",
    parts: [
      {
        paths: [ellipse(C, R, R), ellipse(C, R, 30)],
        faint: [ellipse(C, 38, R)],
        accent: [
          poly(
            [
              [C[0] - 9, C[1] + 4],
              [C[0] + 7, C[1] - 6],
              [C[0] + 11, C[1] + 2],
              [C[0] - 5, C[1] + 12],
            ],
            2,
          ),
        ],
        move: [0, 0],
        callout: { from: at(212, R), to: [70, 560], text: "UHV CHAMBER" },
      },
      {
        paths: port(158, R, 118, 24),
        accent: [`M${f(beamFrom[0])} ${f(beamFrom[1])}L${f(C[0])} ${f(C[1])}`],
        move: outward(158, 46),
        callout: { from: sourceEnd, to: [70, 230], text: "X-RAY SOURCE" },
      },
      {
        paths: [
          ...port(52, R, 92, 20),
          shell(108),
          shell(70),
          seg([A[0] - 108, A[1]], [A[0] + 108, A[1]], 6),
          ellipse(A, 108, 24),
        ],
        faint: [shell(89)],
        move: outward(52, 40),
        callout: {
          from: [A[0] + 76, A[1] - 76],
          to: [800, 96],
          text: "ANALYSER",
        },
      },
      {
        paths: [
          ...port(-12, R, 30, 30),
          ...port(-12, R + 46, 118, 26),
          poly([
            [lock[0] - 8, lock[1] - 40],
            [lock[0] + 20, lock[1] - 46],
            [lock[0] + 20, lock[1] + 34],
            [lock[0] - 8, lock[1] + 40],
          ]),
        ],
        move: outward(-12, 54),
        callout: { from: at(-12, R + 164), to: [760, 380], text: "LOAD LOCK" },
      },
      {
        paths: [
          ...port(96, R, 34, 18),
          seg([rodBase[0] - 3, rodBase[1]], [rod[0] - 3, rod[1]], 4),
          seg([rodBase[0] + 3, rodBase[1]], [rod[0] + 3, rod[1]], 4),
          ellipse(rod, 16, 6),
          `M${[0, 1, 2, 3, 4, 5]
            .map((i) => {
              const p = at(96, R + 50 + i * 12);
              return `${f(p[0] + (i % 2 ? 11 : -11))} ${f(p[1])}`;
            })
            .join("L")}`,
        ],
        move: outward(96, 50),
        callout: { from: rod, to: [210, 70], text: "MANIPULATOR" },
      },
      {
        paths: [
          ...port(-90, R, 70, 26),
          ...upright([turbo[0], turbo[1] + 58], 44, 13, 58),
          ...[0, 60, 120].map((d) =>
            seg(
              [
                turbo[0] + 30 * Math.cos(rad(d)),
                turbo[1] + 9 * Math.sin(rad(d)),
              ],
              [
                turbo[0] - 30 * Math.cos(rad(d)),
                turbo[1] - 9 * Math.sin(rad(d)),
              ],
              0,
            ),
          ),
        ],
        move: [0, 40],
        callout: {
          from: [turbo[0] - 44, turbo[1] + 30],
          to: [250, 690],
          text: "TURBO PUMP",
        },
      },
    ],
    flows: [
      `M${f(C[0])} ${f(C[1])}L${f(lensEnd[0])} ${f(lensEnd[1])}L${f(A[0] - 89)} ${f(A[1])}A89 89 0 0 1 ${f(A[0] + 89)} ${f(A[1])}`,
    ],
    trace: {
      axes: "M600 690L846 690M600 690L600 600",
      line: trace(
        604,
        688,
        236,
        (t) =>
          6 +
          (1 - t) * 18 +
          peak(t, 0.2, 54, 0.014) +
          peak(t, 0.26, 20, 0.012) +
          peak(t, 0.55, 30, 0.02) +
          peak(t, 0.8, 72, 0.016),
      ),
      labels: [
        [[608, 596], "COUNTS"],
        [[846, 706], "BINDING ENERGY"],
      ],
    },
  };
}

const plates = [hplc(), xps()];
const SHOW = 17000;

function Callout({ from, to, text }: NonNullable<Part["callout"]>) {
  const right = to[0] > from[0];
  const elbow: Point = [to[0] + (right ? -18 : 18), to[1]];
  return (
    <g className={s.callout}>
      <circle cx={from[0]} cy={from[1]} r={3} />
      <path
        d={`M${f(from[0])} ${f(from[1])}L${f(elbow[0])} ${f(elbow[1])}L${f(to[0])} ${f(to[1])}`}
        pathLength={1}
      />
      <text
        x={to[0] + (right ? 6 : -6)}
        y={to[1] + 4}
        textAnchor={right ? "start" : "end"}
      >
        {text}
      </text>
    </g>
  );
}

let order = 0;
// Strokes draw in one after another, so the sketch appears as if being drawn.
function Lines({ paths, className }: { paths: string[]; className?: string }) {
  return (
    <>
      {paths.map((d, i) => (
        <path
          key={`${i}-${d}`}
          d={d}
          pathLength={1}
          className={className}
          style={{ "--n": order++ % 48 } as CSSProperties}
        />
      ))}
    </>
  );
}

export default function SketchTwin({ className }: { className?: string }) {
  const id = useId().replace(/:/g, "");
  const [still] = useState(
    () =>
      typeof window !== "undefined" &&
      Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches),
  );
  const [index, setIndex] = useState(0);
  useEffect(() => {
    if (still) return;
    const timer = window.setInterval(
      () => setIndex((current) => (current + 1) % plates.length),
      SHOW,
    );
    return () => window.clearInterval(timer);
  }, [still]);
  const plate = plates[index];
  order = 0;
  return (
    <svg
      className={`${s.sketch} ${className ?? ""}`}
      viewBox="0 0 860 720"
      aria-hidden="true"
      focusable="false"
      data-plate={plate.name}
    >
      <defs>
        <filter id={`pencil-${id}`} x="-5%" y="-5%" width="110%" height="110%">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.022"
            numOctaves="2"
            seed="1"
          >
            {!still && (
              <animate
                attributeName="seed"
                values="1;4;7"
                dur="1.5s"
                calcMode="discrete"
                repeatCount="indefinite"
              />
            )}
          </feTurbulence>
          <feDisplacementMap in="SourceGraphic" scale="3" />
        </filter>
      </defs>
      <g
        key={plate.name}
        className={still ? undefined : s.plate}
        filter={`url(#pencil-${id})`}
      >
        {plate.parts.map((part, i) => (
          <g
            key={i}
            className={s.part}
            style={
              {
                "--dx": `${part.move[0]}px`,
                "--dy": `${part.move[1]}px`,
                "--k": i,
              } as CSSProperties
            }
          >
            <Lines paths={part.paths} />
            {part.faint && <Lines paths={part.faint} className={s.faint} />}
            {part.accent && <Lines paths={part.accent} className={s.accent} />}
            {part.dots?.map(([x, y]) => (
              <circle
                key={`${x}-${y}`}
                className={s.well}
                cx={x}
                cy={y}
                r={2.6}
              />
            ))}
            {part.callout && <Callout {...part.callout} />}
          </g>
        ))}
        {!still &&
          plate.flows.flatMap((path, i) =>
            [0, 1, 2].map((n) => (
              <circle key={`${i}-${n}`} className={s.drop} r={3}>
                <animateMotion
                  dur="2.6s"
                  begin={`${n * 0.85 + i * 0.4}s`}
                  repeatCount="indefinite"
                  path={path}
                />
              </circle>
            )),
          )}
        <g className={s.trace}>
          <path d={plate.trace.axes} pathLength={1} />
          <path className={s.signal} d={plate.trace.line} pathLength={1} />
          {plate.trace.labels.map(([[x, y], text]) => (
            <text key={text} x={x} y={y} textAnchor={x > 700 ? "end" : "start"}>
              {text}
            </text>
          ))}
        </g>
      </g>
    </svg>
  );
}
