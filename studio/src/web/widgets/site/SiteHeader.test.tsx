import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SiteHeader } from "./SiteHeader";

describe("SiteHeader", () => {
  it("uses the Keraun bolt by default", () => {
    const { container } = render(<SiteHeader />);

    expect(screen.getByRole("link", { name: "KERAUN home" })).toBeInTheDocument();
    expect(container.querySelector(".brand-bolt__shell")).toHaveAttribute("d");
    expect(container.querySelector(".brand-bolt__core")).toHaveAttribute("d");
  });

  it("shows Google Cloud setup to authenticated users and routes through the application", async () => {
    const user = userEvent.setup();
    const navigate = vi.fn();
    render(<SiteHeader authStatus="authenticated" dashboardRoute="/dashboard" onNavigate={navigate} />);

    await user.click(screen.getByRole("link", { name: /Google Cloud/i }));

    expect(navigate).toHaveBeenCalledWith("/settings/cloud");
  });

  it("does not expose protected cloud setup to anonymous visitors", () => {
    render(<SiteHeader authStatus="anonymous" dashboardRoute="/dashboard" />);

    expect(screen.queryByRole("link", { name: /Google Cloud/i })).not.toBeInTheDocument();
  });
});
