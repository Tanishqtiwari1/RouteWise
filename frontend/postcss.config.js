import { fileURLToPath } from "node:url";

// Absolute config path so builds work regardless of the current working directory.
export default {
  plugins: {
    tailwindcss: { config: fileURLToPath(new URL("./tailwind.config.js", import.meta.url)) },
    autoprefixer: {},
  },
};
