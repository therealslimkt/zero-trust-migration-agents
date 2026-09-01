import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LandingPage } from "./LandingPage";

describe("LandingPage control surface", () => {
  it("keeps the evidence promise and four capability blocks structurally distinct", () => {
    const { container } = render(<LandingPage />);

    expect(screen.getByRole("heading", { name: /Evidence appears when the system can prove it/i })).toBeInTheDocument();
    expect(screen.getByText(/Configured data speaks; absent data stays absent/i)).toBeInTheDocument();
    // Scoped to the control surface rather than counting every h3 on the page.
    // The assertion is that these four blocks stay structurally distinct, and
    // an unrelated section gaining a subheading is not that failing.
    const capabilities = container.querySelectorAll(".landing-tech-grid .landing-tech-card h3");
    expect(capabilities).toHaveLength(4);
    expect([...capabilities].map((heading) => heading.textContent)).toEqual([
      "Private-source review",
      "Gemini 3.7 Flash",
      "Governed execution",
      "Destination review",
    ]);
  });
});
