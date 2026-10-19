/**
 * How the console names a student: by the name the teacher knows them by, never by the
 * internal reference (`student_ref`) or a paper id. A teacher knows "Dana Levi", not
 * `c7b-0003-…`. The reference shows only as a small tag beside a name another student in the
 * same list shares, so two Dana Levis can still be told apart.
 */

export interface Named {
  student_ref?: string | null;
  full_name?: string | null;
}

/** The text that names one student. A paper filed under nobody reads as such; a student with
 * no name on the list (an old class made before names were required) falls back to the
 * reference, which is then the only name there is. */
export function studentName(student: Named, nobody = "No student matched"): string {
  const name = (student.full_name ?? "").trim();
  if (name !== "") return name;
  const ref = (student.student_ref ?? "").trim();
  if (ref === "" || ref === "unknown") return nobody;
  return ref;
}

/** The names shared by more than one student in `students` — the ones whose reference is
 * shown beside the name to tell them apart. */
export function sharedNames(students: readonly Named[]): Set<string> {
  const counts = new Map<string, number>();
  for (const student of students) {
    const name = (student.full_name ?? "").trim().toLocaleLowerCase();
    if (name !== "") counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return new Set([...counts].filter(([, n]) => n > 1).map(([name]) => name));
}

/** The small tag that tells apart two students with the same name, or null when the name
 * alone is enough. */
export function disambiguator(student: Named, shared: Set<string>): string | null {
  const name = (student.full_name ?? "").trim().toLocaleLowerCase();
  if (name === "" || !shared.has(name)) return null;
  return student.student_ref ?? null;
}

/** A name with its tag folded in, for places that take plain text (a select's options, a
 * confirmation sentence). */
export function studentLabel(student: Named, shared: Set<string>, nobody?: string): string {
  const tag = disambiguator(student, shared);
  const name = studentName(student, nobody);
  return tag === null ? name : `${name} (${tag})`;
}
