import { fileURLToPath } from "node:url";
import { defineConfig, mergeConfig } from "vite";
import appConfig from "./vite.config.ts";

const fixture = name => fileURLToPath(new URL("./guest/" + name, import.meta.url));

export default mergeConfig(appConfig, defineConfig({
  base: "/demo/",
  publicDir: false,
  plugins: [{
    name: "public-demo-fixtures",
    generateBundle(_, files) {
      for (const file of Object.values(files)) {
        if (file.type === "chunk" && Object.keys(file.modules).some(id =>
          !id.includes("/node_modules/") && /\/src\/.*\.json(?:\?|$)/.test(id))) {
          this.error("Use a public guest fixture for dashboard data.");
        }
      }
    },
  }],
  define: {
    "import.meta.env.VITE_MANTI_GUEST": JSON.stringify("1"),
    "import.meta.env.VITE_SOONY_HOSTED_REPLAY": JSON.stringify("0"),
  },
  resolve: {
    alias: [
      { find: "./mock/dashboard.json", replacement: fixture("dashboard.json") },
      { find: "./offers-sample.json", replacement: fixture("offers.json") },
    ],
  },
  build: { outDir: "dist/demo" },
}));
