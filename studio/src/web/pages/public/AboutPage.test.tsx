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
  });

  it("shows the factory line that builds the cartridges", () => {
    const { container } = render(<AboutPage />);

    expect(screen.getByRole("heading", { name: /A legacy engine goes in; a sealed cartridge comes out/i })).toBeInTheDocument();
    // The belt is decorative; the stations carry the same three steps as text so
    // the section still says something to a reader who cannot watch it move.
    expect([...container.querySelectorAll(".pf-station strong")].map((n) => n.textContent))
      .toEqual(["Read", "Decode", "Certify"]);
    expect(container.querySelector(".plugin-factory__line")).toHaveAttribute("aria-hidden", "true");
  });
});

describe("AboutPage creator spotlight", () => {
  it("names the author, frames the portrait, and lists every identity facet", () => {
    const { container } = render(<AboutPage />);

    expect(screen.getByRole("heading", { name: "Katie O’Halloran", level: 3 })).toBeInTheDocument();
    expect(screen.getByAltText("Katie O’Halloran")).toBeInTheDocument();

    for (const word of ["Creator", "Artist", "Architect", "Explorer"]) {
      expect(screen.getByText(word, { selector: ".creator-facet__word" })).toBeInTheDocument();
    }

    // The phrase animates letter by letter, so it is split across spans. It has
    // to keep reading as one line for anyone using a screen reader.
    expect(container.querySelector(".creator-spotlight__phrase")?.textContent).toBe("Dancing Through Life");
    expect(container.querySelectorAll(".creator-spotlight__letter")).toHaveLength(18);
  });

  it("omits the contributor grid until creators are supplied", () => {
    const { container } = render(<AboutPage />);

    expect(container.querySelector(".about-creators-grid")).toBeNull();
    expect(screen.queryByText(/No creator or contributor information/i)).not.toBeInTheDocument();
  });
});
