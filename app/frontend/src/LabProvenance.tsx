import { ExternalLink } from "lucide-react";
import type { Instrument, Lab } from "./cloudlabFacts";

/** Where the listing comes from: the cloud lab's page, or the AC reference and the docs. */
export default function LabProvenance({
  lab,
  item,
}: {
  lab: Lab;
  item: Instrument;
}) {
  if (lab.id === "ecl")
    return (
      <>
        <a href={lab.source} target="_blank" rel="noreferrer">
          {lab.provider} instrumentation{" "}
          <ExternalLink size={12} aria-hidden="true" />
        </a>{" "}
        · read {lab.retrieved}
      </>
    );
  return (
    <>
      Listed in the {lab.source}, received {lab.retrieved}
      {item.url && (
        <>
          {" · "}
          <a href={item.url} target="_blank" rel="noreferrer">
            Documentation <ExternalLink size={12} aria-hidden="true" />
          </a>
        </>
      )}
    </>
  );
}
