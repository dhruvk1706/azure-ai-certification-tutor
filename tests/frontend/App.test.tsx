import { renderToString } from "react-dom/server";
import { expect, test } from "vitest";
import App from "../../frontend/src/App";

test("renders the project name", () => {
  expect(renderToString(<App />)).toContain("Azure AI Certification Tutor");
});
