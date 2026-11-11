import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";

class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("UknowApp render error:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <main style={{ maxWidth: 760, margin: "48px auto", padding: 24, fontFamily: "system-ui, sans-serif", color: "#26334a" }}>
          <h1 style={{ fontSize: 22 }}>Не удалось отобразить интерфейс UknowApp</h1>
          <p>Скопируй текст ошибки ниже и отправь его для исправления.</p>
          <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", padding: 16, borderRadius: 10, background: "#fff1ef", color: "#9d3f35", fontSize: 13 }}>
            {this.state.error.stack || this.state.error.message}
          </pre>
        </main>
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </React.StrictMode>
);
