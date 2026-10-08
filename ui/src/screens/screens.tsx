import { Screen } from "../components/Screen";

/**
 * The screens' shared leftovers: a route the table does not name. Each real screen lives in
 * its own module beside this one (one lifecycle screen, one file), so a screen's DOM and its
 * read are read together.
 */
export function NotFound() {
  return (
    <Screen title="Not found">
      <p>That address is not one of the console's screens. Use the home hub.</p>
    </Screen>
  );
}
