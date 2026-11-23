import { defineConfig } from "vite";
import solid from "@solidjs/vite-plugin";
import { fileURLToPath } from "node:url";
import { compile } from "sass";

const criticalStyle = fileURLToPath(new URL("./src/shared/styles/critical.scss", import.meta.url));

function criticalStylesheet() {
  return {
    name: "critical-stylesheet",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        if (request.url?.split("?")[0] !== "/critical.css") return next();
        response.setHeader("Content-Type", "text/css; charset=utf-8");
        response.end(compile(criticalStyle, { style: "compressed" }).css);
      });
    },
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: "critical.css",
        source: compile(criticalStyle, { style: "compressed" }).css,
      });
    },
  };
}

export default defineConfig({
  plugins: [solid(), criticalStylesheet()],
  server: {
    host: "127.0.0.1",
    port: 22222,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true
      }
    }
  }
});
