import { useEffect, useState, type ComponentType, type ReactElement } from "react";
import type { HubState } from "./api";
import { DESTINATIONS } from "./destinations";
import { Navigate } from "./navigate";
import { Hub } from "./screens/Hub";
import { BlindSample } from "./screens/BlindSample";
import { Help } from "./screens/Help";
import { StudentDetail } from "./screens/StudentDetail";
import { ClassSetup, Monitor, NotFound, Papers, PackageSetup, Results, Review, RunStart, SystemStatus } from "./screens/screens";
import { useHubState } from "./useHubState";

/**
 * The console's shell. Hash-based routing: the server answers only `/` and `/assets/…` and
 * owes an unknown path a 404, so the routes live in the fragment (`#/review`) and navigation
 * never leaves the origin. The hub's cards are the shell's navigation — one link per
 * destination (FR-UI-02), present beside every screen, so each destination stays one click
 * away from wherever the teacher is.
 */
type ScreenProps = { state: HubState | null };
type ScreenComponent = ComponentType<ScreenProps>;

const ROUTES: Record<string, ScreenComponent> = {
  "/": Hub,
  "/package": PackageSetup,
  "/class": ClassSetup,
  "/papers": Papers,
  "/run": RunStart,
  "/monitor": Monitor,
  "/review": Review,
  "/results": Results,
  "/help": Help,
  "/status": SystemStatus,
};

/** A results row's student link: `#/results/students/<submission id>`. */
const STUDENT_ROUTE = /^\/results\/students\/([^/]+)$/;

function routeOf(hash: string): string {
  const path = hash.replace(/^#/, "");
  return path.startsWith("/") ? path : "/";
}

export function App() {
  const [route, setRoute] = useState<string>(() => routeOf(window.location.hash));
  const hub = useHubState();

  useEffect(() => {
    const follow = (): void => setRoute(routeOf(window.location.hash));
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);

  const student = STUDENT_ROUTE.exec(route);
  let screen: ReactElement;
  if (student !== null) {
    screen = <StudentDetail submissionId={student[1] ?? ""} />;
  } else if (route === "/review/blind") {
    screen = <BlindSample />;
  } else {
    const Screen = ROUTES[route] ?? NotFound;
    screen = <Screen state={hub.state} />;
  }
  return (
    <Navigate.Provider value={setRoute}>
      <nav className="hub" aria-label="Console destinations">
        <ul className="hub-grid">
          {DESTINATIONS.map((destination) => (
            <li key={destination.path}>
              <a
                className="card"
                href={`#${destination.path}`}
                onClick={() => setRoute(destination.path)}
              >
                <h2>{destination.title}</h2>
                <p className="card-note">{destination.note}</p>
                {destination.path === "/run" && hub.state !== null && (
                  <p className="card-state">Engine in force: {hub.state.engine}</p>
                )}
              </a>
            </li>
          ))}
        </ul>
      </nav>
      <main className="screen">
        {/* The hub's own alert rides the hub route alone (CT-UI-04): a screen's error is the
            screen's own named message, so one screen's failure never answers for another. */}
        {route === "/" && hub.failed && (
          <p role="alert" className="hub-alert">
            The console could not read its state. It will keep trying.
          </p>
        )}
        {screen}
      </main>
    </Navigate.Provider>
  );
}
