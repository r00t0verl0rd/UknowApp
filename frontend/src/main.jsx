import { createRoot } from "react-dom/client";
import App from "./app/App.jsx";
import "./shared/styles/index.css";

createRoot(document.getElementById("root")).render(<React.StrictMode><App /></React.StrictMode>);
