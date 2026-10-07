import { Screen } from "../components/Screen";
import { DESTINATIONS } from "../destinations";

/**
 * The eight destination screens' foundation: each loads in one click from the hub and carries
 * its `main` landmark and level-1 heading (the DOM contract in `tests/support/spa.py`). Their
 * working content is the lifecycle stories' work — the hub's home is `Hub.tsx`, and the Q&A
 * panel arrives with the manuals story.
 */
const NOTES = new Map(DESTINATIONS.map((destination) => [destination.path, destination.note]));

function destinationScreen(path: string, title: string) {
  return function DestinationScreen() {
    return (
      <Screen title={title}>
        <p>{NOTES.get(path)}</p>
      </Screen>
    );
  };
}

export const PackageSetup = destinationScreen("/package", "Set up a test package");
export const ClassSetup = destinationScreen("/class", "Set up a class");
export const Papers = destinationScreen("/papers", "Load papers");
export const RunStart = destinationScreen("/run", "Start a run");
export const Monitor = destinationScreen("/monitor", "Monitor run");
export const Review = destinationScreen("/review", "Review queue");
export const Results = destinationScreen("/results", "Results");
export const Help = destinationScreen("/help", "Manuals & help");
export const SystemStatus = destinationScreen("/status", "System status");

export function NotFound() {
  return (
    <Screen title="Not found">
      <p>That address is not one of the console's screens. Use the home hub.</p>
    </Screen>
  );
}
