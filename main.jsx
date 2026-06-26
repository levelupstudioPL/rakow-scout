import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

const style = document.createElement("style");
style.textContent = `
  html,body,#root{margin:0;padding:0;background:#0E1412;min-height:100%;}
`;
document.head.appendChild(style);

createRoot(document.getElementById("root")).render(<App />);
