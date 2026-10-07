import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

/**
 * CT-UI-01 / RISK-108: the console serves schools with no internet, so no byte of the built
 * bundle may name an external origin — the whole bundle is swept for `http(s)://` URLs, fonts
 * included. React's production error text embeds the address of its error decoder; the
 * console shows the error code on its own error screens, never a web address a classroom
 * machine cannot reach. The rewrites are text-only (an error string, never a fetch) and are
 * applied at build time so the committed bundle is already clean.
 */
const EXTERNAL_ORIGIN_TEXT_REWRITES: ReadonlyArray<readonly [string, string]> = [
  ["https://react.dev/errors/", "/#"],
];

function noExternalOrigins(): Plugin {
  return {
    name: "aeh-no-external-origins",
    apply: "build",
    renderChunk(code: string, chunk) {
      let rewritten = code;
      for (const [external, local] of EXTERNAL_ORIGIN_TEXT_REWRITES) {
        if (rewritten.includes(external)) {
          rewritten = rewritten.split(external).join(local);
        }
      }
      return rewritten === code ? null : { code: rewritten, map: null };
    },
  };
}

export default defineConfig({
  base: "/",
  plugins: [react(), noExternalOrigins()],
  build: {
    assetsDir: "assets",
    sourcemap: false,
  },
});
