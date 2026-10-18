import { useEffect, useMemo, useState, type ComponentType, type ReactElement } from "react";
import type { ContextDoc } from "./api";
import { HelpPanel } from "./components/HelpPanel";
import { Navigate, type SelectionPatch } from "./navigate";
import { SelectionContext } from "./selection";
import { BlindSample } from "./screens/BlindSample";
import { ClassSetup } from "./screens/ClassSetup";
import { DraftEditor } from "./screens/DraftEditor";
import { Help } from "./screens/Help";
import { Issues } from "./screens/Issues";
import { Jobs } from "./screens/Jobs";
import { Logs } from "./screens/Logs";
import { Monitor } from "./screens/Monitor";
import { PackageSetup } from "./screens/PackageSetup";
import { PackageAuthor } from "./screens/PackageAuthor";
import { Parked } from "./screens/Parked";
import { Papers } from "./screens/Papers";
import { Results } from "./screens/Results";
import { Review } from "./screens/Review";
import { ReviewDraft } from "./screens/ReviewDraft";
import { RunStart } from "./screens/RunStart";
import { Settings } from "./screens/Settings";
import { StudentDetail } from "./screens/StudentDetail";
import { SystemStatus } from "./screens/SystemStatus";
import { NotFound } from "./screens/screens";
import { useContextPoll } from "./useContextPoll";
import { ContextHeader } from "./wizard/ContextHeader";
import {
  deriveWizard,
  impactLine,
  nextLine,
  resolveSelection,
  type Selection,
} from "./wizard/derivation";
import { Sidebar } from "./wizard/Sidebar";
import { WizardHome } from "./wizard/WizardHome";
import { useWizardReads } from "./wizard/useWizardReads";
import { ToastHost } from "./state/StateDisplay";

/**
 * The console's shell (FR-CONSOLE-47). Hash-based routing: the server answers only `/` and
 * `/assets/…` and owes an unknown path a 404, so the routes live in the fragment and
 * navigation never leaves the origin. The wizard is the hub — the wizard home at `/`, the
 * context header and the sidebar ride every screen, and the address carries the teacher's
 * selection (class, package, run) as opaque refs in the fragment's query, never anything
 * stored (`CT-UI-07`).
 */

/** The lifecycle screens the redesign keeps; later stories fill the remaining routes. */
const ROUTES: Record<string, ComponentType> = {
  "/monitor": Monitor,
  "/review": Review,
  "/results": Results,
  "/status": SystemStatus,
};

/** A results row's student link: `#/results/students/<submission id>`. */
const STUDENT_ROUTE = /^\/results\/students\/([^/]+)$/;

/** The selection keys the address carries (`CT-UI-07`: opaque refs, nothing else). */
const SELECTION_KEYS = ["class", "package", "run"] as const;

interface Address {
  path: string;
  params: URLSearchParams;
}

/** An empty document: what the wizard derives from before the context read has answered. */
const EMPTY_CONTEXT: ContextDoc = { classes: [], cohorts: [], packages: [], runs: [] };

function addressOf(hash: string): Address {
  const raw = hash.replace(/^#/, "");
  if (!raw.startsWith("/")) {
    return { path: "/", params: new URLSearchParams() };
  }
  const mark = raw.indexOf("?");
  if (mark === -1) {
    return { path: raw, params: new URLSearchParams() };
  }
  return { path: raw.slice(0, mark), params: new URLSearchParams(raw.slice(mark + 1)) };
}

export function App() {
  const [address, setAddress] = useState<Address>(() => addressOf(window.location.hash));
  const [helpOpen, setHelpOpen] = useState(false);
  const { context, failed, retry } = useContextPoll();

  useEffect(() => {
    const follow = (): void => setAddress(addressOf(window.location.hash));
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);

  // The selection: the address's explicit refs win when they still name something; the
  // rest falls back to what the context read can stand behind (a lone entity selects
  // itself, a selected run names its package, the class's newest run is in focus).
  const selection = useMemo<Selection>(
    () =>
      resolveSelection(context ?? EMPTY_CONTEXT, {
        class: address.params.get("class") ?? undefined,
        package: address.params.get("package") ?? undefined,
        run: address.params.get("run") ?? undefined,
      }),
    [context, address],
  );

  // The supplemental reads live in the shell, not on the wizard home: the compact strip on
  // every secondary page and the full stepper derive from the same answered reads, so no
  // stage state is ever rendered from the absence of a read.
  const reads = useWizardReads(context, selection);

  // One derivation, feeding both the wizard home's full rows and the sidebar's strip.
  const rows = useMemo(
    () =>
      deriveWizard(context ?? EMPTY_CONTEXT, selection, {
        papers: reads.papers.data,
        parked: reads.parked.data,
        jobs: reads.jobs.data,
        impact: reads.impact.data,
      }),
    [context, selection, reads],
  );
  const next = useMemo(() => nextLine(rows), [rows]);
  // The IMPACT line: the impact read's own wording; with no published version to read, the
  // context alone answers — nothing unpublished can have anything downstream.
  const impact =
    reads.impact.data !== null
      ? impactLine(reads.impact.data)
      : context !== null && reads.publishedVersion === null
        ? "Nothing downstream yet."
        : null;
  const readsFailed =
    failed ||
    reads.papers.error !== null ||
    reads.parked.error !== null ||
    reads.jobs.error !== null ||
    reads.impact.error !== null;
  // Which runs are actually paused: the jobs read mirrors a paused run's job as
  // `running`, so the jobs page takes the real states from here (the context read's own).
  const pausedRunIds = useMemo(
    () =>
      context === null
        ? []
        : context.runs
            .filter((run) => run.state === "paused")
            .map((run) => run.run_id),
    [context],
  );
  const retryAll = (): void => {
    retry();
    reads.papers.retry();
    reads.parked.retry();
    reads.jobs.retry();
    reads.impact.retry();
  };

  const threadedQuery = useMemo(() => {
    const params = new URLSearchParams();
    for (const key of SELECTION_KEYS) {
      const value = address.params.get(key);
      if (value !== null) {
        params.set(key, value);
      }
    }
    const query = params.toString();
    return query === "" ? "" : `?${query}`;
  }, [address]);
  const stageHref = useMemo(
    () => (stageRoute: string) => `#${stageRoute}${threadedQuery}`,
    [threadedQuery],
  );

  /** One navigation: set the fragment, keeping the selection threaded through it. */
  const goTo = (path: string, patch?: SelectionPatch): void => {
    const params = new URLSearchParams(address.params);
    if (patch !== undefined) {
      for (const key of SELECTION_KEYS) {
        const value = patch[key];
        if (value === undefined) continue;
        if (value === null) {
          params.delete(key);
        } else {
          params.set(key, value);
        }
      }
    }
    const query = params.toString();
    window.location.hash = `#${path}${query === "" ? "" : `?${query}`}`;
  };

  const student = STUDENT_ROUTE.exec(address.path);
  let screen: ReactElement;
  if (student !== null) {
    screen = <StudentDetail submissionId={student[1] ?? ""} />;
  } else if (address.path === "/review/blind") {
    screen = <BlindSample />;
  } else if (address.path === "/help") {
    // The help screen reads nothing of its own (TC-REQ-129), so its degradation
    // (FR-UI-07) rides the shell's context read's failure: a named message and the
    // context read's retry, the same recoverable shape every other screen renders.
    screen = <Help failed={failed} onRetry={retry} />;
  } else if (address.path === "/") {
    screen = (
      <WizardHome
        rows={rows}
        next={next}
        impact={impact}
        stageHref={stageHref}
        failed={readsFailed}
        retry={retryAll}
      />
    );
  } else if (address.path === "/package") {
    screen = <PackageSetup context={context} />;
  } else if (address.path === "/class") {
    screen = <ClassSetup classId={selection.classId} />;
  } else if (address.path === "/papers") {
    screen = <Papers context={context} selection={selection} />;
  } else if (address.path === "/run") {
    screen = <RunStart context={context} selection={selection} />;
  } else if (address.path === "/issues") {
    screen = <Issues runId={selection.runId} />;
  } else if (address.path === "/logs") {
    screen = <Logs runId={selection.runId} />;
  } else if (address.path === "/parked") {
    screen = <Parked />;
  } else if (address.path === "/jobs") {
    screen = <Jobs pausedRunIds={pausedRunIds} />;
  } else if (address.path === "/settings") {
    screen = <Settings />;
  } else if (address.path === "/package/author") {
    screen = <PackageAuthor packageId={selection.packageId} />;
  } else if (address.path === "/package/review") {
    screen = <ReviewDraft packageId={selection.packageId} />;
  } else if (address.path === "/package/edit") {
    screen = (
      <DraftEditor
        packageId={selection.packageId}
        publishedVersion={reads.publishedVersion}
        impact={reads.impact}
      />
    );
  } else {
    const Route = ROUTES[address.path];
    if (Route !== undefined) {
      screen = <Route />;
    } else {
      screen = <NotFound />;
    }
  }

  return (
    <Navigate.Provider value={goTo}>
      <SelectionContext.Provider value={selection}>
      <ToastHost>
        <div className="shell">
          <ContextHeader
            context={context}
            selection={selection}
            onSelection={(patch) => goTo(address.path, patch)}
            onHelp={() => setHelpOpen(!helpOpen)}
            helpOpen={helpOpen}
          />
          <div className="shell-body">
            <Sidebar
              rows={context === null ? null : rows}
              route={address.path}
              stageHref={stageHref}
            />
            <main className="screen">{screen}</main>
          </div>
          {helpOpen && (
            <HelpPanel
              route={address.path}
              refs={[
                selection.classId,
                selection.packageId,
                selection.runId,
              ].filter((ref): ref is string => ref !== null)}
              onClose={() => setHelpOpen(false)}
            />
          )}
        </div>
      </ToastHost>
      </SelectionContext.Provider>
    </Navigate.Provider>
  );
}
