import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LandingPage } from "./LandingPage";

describe("LandingPage control surface", () => {
  it("keeps the evidence promise and four capability blocks structurally distinct", () => {
    render(<LandingPage />);

    expect(screen.getByRole("heading", { name: /Evidence appears when the system can prove it/i })).toBeInTheDocument();
    expect(screen.getByText(/Configured data speaks; absent data stays absent/i)).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(4);
    expect(screen.getByRole("heading", { name: "Private-source review" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Destination review" })).toBeInTheDocument();
  });
});
