import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import "./styles/layout.css";  // SOTA Layout System
import "./styles/responsive.css";  // SOTA Responsive Classes (CSS Media Queries)
import App from "./App";
// SOTA: Zustand handles global state - no Context provider needed

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
