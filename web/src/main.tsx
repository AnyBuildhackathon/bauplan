import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { initSource } from "./events/source";
import "./index.css";

initSource();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
