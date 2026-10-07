/**
 * The hub's nine destinations (FR-UI-02) and their routes — the SPA's one table of where a
 * teacher goes from home. The card titles are the destinations' wording; the cards' notes say
 * what each screen is for in one line.
 */
export interface Destination {
  path: string;
  title: string;
  note: string;
}

export const DESTINATIONS: readonly Destination[] = [
  {
    path: "/package",
    title: "Set up a test package",
    note: "Choose and build the package the class is graded against.",
  },
  {
    path: "/class",
    title: "Set up a class",
    note: "Name the students and their consent classes.",
  },
  {
    path: "/papers",
    title: "Load papers",
    note: "Upload each student's scanned papers.",
  },
  {
    path: "/run",
    title: "Start a run",
    note: "Grade the whole cohort with the engine setting in force.",
  },
  {
    path: "/monitor",
    title: "Monitor run",
    note: "Watch progress while grading proceeds.",
  },
  {
    path: "/review",
    title: "Review queue",
    note: "Check flagged answers before grades are final.",
  },
  {
    path: "/results",
    title: "Results",
    note: "Each student's grade, then finalize.",
  },
  {
    path: "/help",
    title: "Manuals & help",
    note: "Ask the manuals or read the guide.",
  },
  {
    path: "/status",
    title: "System status",
    note: "The console, the store and the run.",
  },
];
