import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
    plugins: [react()],
    build: {
        rollupOptions: {
            output: {
                // The standalone sign-in and fallback pages share this URL with the app.
                assetFileNames: function (asset) { return asset.names.indexOf("manti-logo.png") >= 0 ? "brand/manti-logo.png" : "assets/[name]-[hash][extname]"; },
            },
        },
    },
    server: {
        proxy: {
            "/api": "http://127.0.0.1:8787",
        },
    },
});
