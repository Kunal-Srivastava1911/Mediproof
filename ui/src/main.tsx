import React from "react";
import ReactDOM from "react-dom/client";
import ReviewApp from "./ReviewApp";
import SubmitApp from "./SubmitApp";
import "./index.css";

const Root = window.location.pathname.startsWith("/review") ? ReviewApp : SubmitApp;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
