import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AssistantXmlProofApp } from "./AssistantXmlProofApp";
import "./styles.css";

const root = document.getElementById("root");

if (root) {
  createRoot(root).render(
    <StrictMode>
      <AssistantXmlProofApp />
    </StrictMode>,
  );
}
