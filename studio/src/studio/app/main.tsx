import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "../../design-system/theme/global.css";
import "./studio.css";
import { App } from "./App.js";
import { StudioProviders } from "./providers/StudioProviders.js";

const root = document.getElementById("root");
if (!root) throw new Error("Skin Studio root element was not found");

createRoot(root).render(
  <StrictMode>
    <StudioProviders>
      <App />
    </StudioProviders>
  </StrictMode>,
);

