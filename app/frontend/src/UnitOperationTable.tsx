import type { Twin } from "./instrumentTypes";
import {
  families,
  reach,
  unitOperations,
  type Reach,
  type UnitOperation,
} from "./unitOperations";
import s from "./UnitOperationTable.module.css";

const LEGEND: Record<Reach["kind"], string> = {
  lab: "Lab connector",
  mock: "Mock connector",
  absent: "No instrument here",
  stub: "No command yet",
};

/**
 * The unit operations as a table: one column per family, each tile in its fixed place.
 * Its material says how far it runs in this workcell; picking one adds it as a step.
 */
export default function UnitOperationTable({
  twins,
  disabled,
  onPick,
}: {
  twins: Twin[];
  disabled: boolean;
  onPick: (op: UnitOperation, device: Twin) => void;
}) {
  const reaches = new Map(
    unitOperations.map((op) => [op.id, reach(op, twins)]),
  );
  const shown = new Set([...reaches.values()].map((r) => r.kind));
  return (
    <div className={s.library}>
      <div className={s.scroll}>
        <div className={s.table} role="group" aria-label="Unit operations">
          {families.map((family) => (
            <div key={family} className={s.family}>
              <h3>{family}</h3>
              {unitOperations
                .filter((op) => op.family === family)
                .map((op) => {
                  const r = reaches.get(op.id)!;
                  const className = `${s.tile} ${s[r.kind]}`;
                  const face = (
                    <>
                      <b>{op.symbol}</b>
                      <span>{op.name}</span>
                    </>
                  );
                  return "device" in r ? (
                    <button
                      key={op.id}
                      className={className}
                      disabled={disabled}
                      aria-label={`Add ${op.name} on ${r.device.spec!.name}`}
                      title={r.device.spec!.name}
                      onClick={() => onPick(op, r.device)}
                    >
                      {face}
                    </button>
                  ) : (
                    <button
                      key={op.id}
                      className={className}
                      disabled
                      aria-label={`${op.name}: ${r.reason}`}
                    >
                      {face}
                      <small>{r.reason}</small>
                    </button>
                  );
                })}
            </div>
          ))}
        </div>
      </div>
      <ul className={s.legend}>
        {(Object.keys(LEGEND) as Reach["kind"][])
          .filter((kind) => shown.has(kind))
          .map((kind) => (
            <li key={kind}>
              <i className={`${s.swatch} ${s[kind]}`} aria-hidden="true" />
              {LEGEND[kind]}
            </li>
          ))}
      </ul>
    </div>
  );
}
