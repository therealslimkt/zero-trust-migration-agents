import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AboutPage } from "./AboutPage";

describe("AboutPage enterprise fleet", () => {
  it("presents named specialists, authority boundaries, and honest hardening targets", () => {
    render(<AboutPage />);

    expect(screen.getByRole("heading", { name: /Specialists with names, contracts, and bounded authority/i })).toBeInTheDocument();
    expect(screen.getByText("ATLAS", { selector: ".about-agent-card header span" })).toBeInTheDocument();
    expect(screen.getByText("JETTY", { selector: ".about-agent-card header span" })).toBeInTheDocument();
    expect(screen.getByText("PRISMA", { selector: ".about-agent-card header span" })).toBeInTheDocument();
    expect(screen.getByText("STEWARD", { selector: ".about-agent-card header span" })).toBeInTheDocument();
    expect(screen.getByText("HARDENING")).toBeInTheDocument();
    expect(screen.getByText(/“Next” items are architectural targets, not demo claims/i)).toBeInTheDocument();
  });
});
