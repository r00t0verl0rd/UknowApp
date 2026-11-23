import { defineConfig } from "vite";
import solid from "@solidjs/vite-plugin";
export default defineConfig({
  plugins: [solid()],
  build: { reportCompressedSize: false },
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
