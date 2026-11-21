import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./app/App.jsx";
import "./shared/styles/index.css";

document.getElementById("web-fonts").media = "all";

createRoot(document.getElementById("root")).render(<StrictMode><App /></StrictMode>);
