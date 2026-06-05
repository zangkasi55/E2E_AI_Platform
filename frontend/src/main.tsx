// =============================================================================
// main.tsx — React entry. BrowserRouter + global styles + <App>.
// =============================================================================
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthGate } from "./components/AuthGate";
import "./styles.css";

const el = document.getElementById("root");
if (!el) throw new Error("Root element #root not found");

createRoot(el).render(
  <StrictMode>
    <AuthGate>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </AuthGate>
  </StrictMode>,
);
