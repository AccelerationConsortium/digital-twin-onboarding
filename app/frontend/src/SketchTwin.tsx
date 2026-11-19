import { useId, type CSSProperties } from "react";
import s from "./SketchTwin.module.css";

/*
 * A hand-drawn anatomy plate of a liquid handler: an oblique line sketch whose
 * parts lift apart and settle back. Decorative only, so it has no accessible name.
 */
type Point = [number, number];
const OX = 150;
const OY = 600;
const W = 480;
const H = 380;
const D = 280;
const DECK = 70;
const RAIL = H - 30;
const BEAM_Z = 140;

const P = (x: number, y: number, z: number): Point => [
  OX + x + z * 0.45,
  OY - y - z * 0.3,
];
const f = (n: number) => n.toFixed(1);
// Sketched edges run a little past their corners, as construction lines do.
function seg(a: Point, b: Point, over = 9) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = Math.hypot(dx, dy) || 1;
  const ux = (dx / len) * over;
  const uy = (dy / len) * over;
  return `M${f(a[0] - ux)} ${f(a[1] - uy)}L${f(b[0] + ux)} ${f(b[1] + uy)}`;
}
const poly = (points: Point[], over = 5) =>
  points.map((p, i) => seg(p, points[(i + 1) % points.length], over)).join("");

function box(
  x0: number,
  y0: number,
  z0: number,
  w: number,
  h: number,
  d: number,
) {
  const c = (x: number, y: number, z: number) => P(x0 + x, y0 + y, z0 + z);
  return [
    poly([c(0, 0, 0), c(w, 0, 0), c(w, h, 0), c(0, h, 0)]),
    poly([c(0, h, 0), c(w, h, 0), c(w, h, d), c(0, h, d)]),
    poly([c(w, 0, 0), c(w, 0, d), c(w, h, d), c(w, h, 0)]),
  ];
}
function wells(
  x0: number,
  z0: number,
  y: number,
  cols: number,
  rows: number,
  pitch: number,
) {
  const out: Point[] = [];
  for (let i = 0; i < cols; i++)
    for (let j = 0; j < rows; j++)
      out.push(P(x0 + pitch * (i + 0.5), y, z0 + pitch * (j + 0.5)));
  return out;
}

const frame = [
  seg(P(0, 0, 0), P(W, 0, 0)),
  seg(P(W, 0, 0), P(W, H, 0)),
  seg(P(W, H, 0), P(0, H, 0)),
  seg(P(0, H, 0), P(0, 0, 0)),
  seg(P(0, H, 0), P(0, H, D)),
  seg(P(W, H, 0), P(W, H, D)),
  seg(P(W, 0, 0), P(W, 0, D)),
  seg(P(0, H, D), P(W, H, D)),
  seg(P(W, H, D), P(W, 0, D)),
  seg(P(0, DECK, 0), P(W, DECK, 0)),
  seg(P(W, DECK, 0), P(W, DECK, D)),
];
const hidden = [
  seg(P(0, 0, D), P(W, 0, D), 0),
  seg(P(0, 0, D), P(0, H, D), 0),
  seg(P(0, 0, D), P(0, 0, 0), 0),
];
const GAP = 12;
const slotW = (W - 40 - GAP * 2) / 3;
const slotD = (D - 40 - GAP * 3) / 4;
const slot = (col: number, row: number) => ({
  x: 20 + col * (slotW + GAP),
  z: 20 + row * (slotD + GAP),
});
const slots = Array.from({ length: 12 }, (_, i) => {
  const { x, z } = slot(i % 3, Math.floor(i / 3));
  return poly(
    [
      P(x, DECK, z),
      P(x + slotW, DECK, z),
      P(x + slotW, DECK, z + slotD),
      P(x, DECK, z + slotD),
    ],
    3,
  );
});
const rails = [
  seg(P(12, RAIL, 10), P(12, RAIL, D - 10), 14),
  seg(P(W - 12, RAIL, 10), P(W - 12, RAIL, D - 10), 14),
];
const beam = box(4, RAIL - 6, BEAM_Z - 10, W - 8, 16, 20);

const tipAt = slot(0, 1);
const plateAt = slot(1, 2);
const reservoirAt = slot(2, 0);
const labware = [
  {
    name: "TIP RACK",
    lift: -60,
    lines: box(tipAt.x + 4, DECK, tipAt.z + 4, slotW - 8, 34, slotD - 8),
    dots: wells(tipAt.x + 10, tipAt.z + 6, DECK + 34, 6, 3, (slotW - 20) / 6),
    anchor: P(tipAt.x + 10, DECK + 34, tipAt.z + 4),
    label: [40, 440] as Point,
  },
  {
    name: "WELL PLATE",
    lift: -86,
    lines: box(plateAt.x + 4, DECK, plateAt.z + 4, slotW - 8, 18, slotD - 8),
    dots: wells(
      plateAt.x + 8,
      plateAt.z + 6,
      DECK + 18,
      8,
      3,
      (slotW - 16) / 8,
    ),
    anchor: P(plateAt.x + slotW - 6, DECK + 18, plateAt.z + slotD - 6),
    label: [700, 260] as Point,
  },
  {
    name: "RESERVOIR",
    lift: -48,
    lines: [
      ...box(
        reservoirAt.x + 4,
        DECK,
        reservoirAt.z + 4,
        slotW - 8,
        26,
        slotD - 8,
      ),
      ...[1, 2, 3].map((i) => {
        const x = reservoirAt.x + 4 + ((slotW - 8) / 4) * i;
        return seg(
          P(x, DECK + 26, reservoirAt.z + 6),
          P(x, DECK + 26, reservoirAt.z + slotD - 10),
          0,
        );
      }),
    ],
    dots: [],
    anchor: P(reservoirAt.x + slotW - 4, DECK, reservoirAt.z + 4),
    label: [742, 560] as Point,
  },
];

const head = box(-26, RAIL - 140, BEAM_Z - 20, 52, 120, 40);
const nozzle = seg(P(0, RAIL - 140, BEAM_Z), P(0, RAIL - 182, BEAM_Z), 0);
const tip = P(0, RAIL - 186, BEAM_Z);
const headTop = P(26, RAIL - 20, BEAM_Z - 20);
const railEnd = P(W - 12, RAIL, 10);
const deckCorner = P(20, DECK, 20);

function Callout({ from, to, text }: { from: Point; to: Point; text: string }) {
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
      {paths.map((d) => (
        <path
          key={d}
          d={d}
          pathLength={1}
          className={className}
          style={{ "--n": order++ % 60 } as CSSProperties}
        />
      ))}
    </>
  );
}

export default function SketchTwin({ className }: { className?: string }) {
  const id = useId().replace(/:/g, "");
  order = 0;
  const still =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  return (
    <svg
      className={`${s.sketch} ${className ?? ""}`}
      viewBox="0 0 860 700"
      aria-hidden="true"
      focusable="false"
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
      <g filter={`url(#pencil-${id})`}>
        <g className={s.base}>
          <Lines paths={hidden} className={s.hidden} />
          <Lines paths={frame} />
          <Lines paths={slots} className={s.faint} />
          <Callout from={deckCorner} to={[60, 640]} text="DECK · 12 SLOTS" />
        </g>
        {labware.map((item, i) => (
          <g
            key={item.name}
            className={s.part}
            style={{ "--lift": `${item.lift}px`, "--k": i } as CSSProperties}
          >
            <Lines paths={item.lines} />
            {item.dots.map(([x, y]) => (
              <circle
                key={`${x}-${y}`}
                className={s.well}
                cx={x}
                cy={y}
                r={2.4}
              />
            ))}
            <Callout from={item.anchor} to={item.label} text={item.name} />
          </g>
        ))}
        <g
          className={s.part}
          style={{ "--lift": "-120px", "--k": 3 } as CSSProperties}
        >
          <Lines paths={rails} />
          <Callout from={railEnd} to={[720, 150]} text="GANTRY" />
          <g className={s.beam}>
            <Lines paths={beam} />
            <g className={s.carriage}>
              <Lines paths={head} />
              <Lines paths={[nozzle]} className={s.accent} />
              <circle className={s.drop} cx={tip[0]} cy={tip[1]} r={4} />
              <Callout
                from={headTop}
                to={[headTop[0] - 170, headTop[1] - 60]}
                text="PIPETTE"
              />
            </g>
          </g>
        </g>
        <g className={s.axes}>
          <path d="M60 560l0-46M60 560l40 0M60 560l22 -15" pathLength={1} />
          <text x={56} y={506}>
            Y
          </text>
          <text x={106} y={564}>
            X
          </text>
          <text x={86} y={540}>
            Z
          </text>
        </g>
      </g>
    </svg>
  );
}
