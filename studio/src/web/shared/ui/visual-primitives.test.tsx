import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const motionPreference = vi.hoisted(() => ({ reduced: false }));

vi.mock("motion/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("motion/react")>();
  return {
    ...actual,
    useReducedMotion: () => motionPreference.reduced,
  };
});

import { PixelIcon } from "./PixelIcon";
import { ReplayBadge } from "./ReplayBadge";
import { StatusBeacon } from "./StatusBeacon";
import { TerminalWindow } from "./TerminalWindow";
import { ThemeToggle } from "./ThemeToggle";

afterEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
  motionPreference.reduced = false;
});

describe("ThemeToggle", () => {
  it("persists an uncontrolled selection and reflects it in the document theme", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle storageKey="visual-primitives-theme" />);

    const toggle = screen.getByRole("switch", {
      name: "Toggle color theme between dark and light",
    });
    expect(toggle).toHaveAttribute("aria-checked", "false");

    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(localStorage.getItem("visual-primitives-theme")).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("does not mutate controlled state before its owner accepts the requested change", async () => {
    const user = userEvent.setup();
    const onThemeChange = vi.fn();
    const view = render(<ThemeToggle theme="dark" onThemeChange={onThemeChange} />);

    const toggle = screen.getByRole("switch");
    await user.click(toggle);

    expect(onThemeChange).toHaveBeenCalledWith("light");
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(localStorage.getItem("pixel-theme")).toBeNull();

    view.rerender(<ThemeToggle theme="light" onThemeChange={onThemeChange} />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});

describe("ReplayBadge", () => {
  it("reports its actual replay metadata and only becomes a button when interactive", async () => {
    const passive = render(
      <ReplayBadge mode="live" timestamp="14:22:08.104" step={3} totalSteps={9} speed="2x" />,
    );

    const liveStatus = screen.getByRole("status");
    expect(liveStatus).toHaveAttribute(
      "aria-label",
      "Playback mode: LIVE, Timestamp: 14:22:08.104, Step 3 of 9, Speed: 2x",
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();

    passive.unmount();

    const user = userEvent.setup();
    const onTogglePlay = vi.fn();
    const onClick = vi.fn();
    render(
      <ReplayBadge
        mode="replay"
        isPlaying={false}
        interactive
        onClick={onClick}
        onTogglePlay={onTogglePlay}
      />,
    );

    const replay = screen.getByRole("button", { name: "Playback mode: REPLAY" });
    await user.click(replay);

    expect(onTogglePlay).toHaveBeenCalledTimes(1);
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe("StatusBeacon", () => {
  it("retains a polite textual status while suppressing animated rings for reduced motion", () => {
    motionPreference.reduced = true;

    const { container } = render(
      <StatusBeacon status="active" label="Protected path active" detail="12ms" showLabel={false} />,
    );

    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveTextContent("Protected path active - 12ms");
    expect(container.querySelector(".status-beacon__ring")).not.toBeInTheDocument();
  });
});

describe("PixelIcon", () => {
  it("is hidden when decorative and exposes an accessible image when named", () => {
    const { container, rerender } = render(<PixelIcon name="shield-check" />);

    const decorative = container.querySelector(".pixel-icon");
    expect(decorative).toHaveAttribute("role", "presentation");
    expect(decorative).toHaveAttribute("aria-hidden", "true");

    rerender(<PixelIcon name="shield-check" title="Verified migration evidence" />);

    expect(screen.getByRole("img", { name: "Verified migration evidence" })).toBeInTheDocument();
    expect(screen.getByText("Verified migration evidence", { selector: "title" })).toBeInTheDocument();
  });
});

describe("TerminalWindow", () => {
  it("minimizes and restores from the focused control button", async () => {
    const user = userEvent.setup();
    const onMinimize = vi.fn();
    render(
      <TerminalWindow title="Evidence trace" onMinimize={onMinimize}>
        <p>Immutable evidence body</p>
      </TerminalWindow>,
    );

    await user.click(screen.getByRole("button", { name: "Minimize window" }));
    await waitFor(() => {
      expect(screen.queryByText("Immutable evidence body")).not.toBeInTheDocument();
    });
    expect(onMinimize).toHaveBeenLastCalledWith(true);

    await user.click(screen.getByRole("button", { name: "Expand window" }));

    await waitFor(() => {
      expect(screen.getByText("Immutable evidence body")).toBeInTheDocument();
    });
    expect(onMinimize).toHaveBeenLastCalledWith(false);
  });

  it("toggles maximize and restore while keeping close unavailable", async () => {
    const user = userEvent.setup();
    const onMaximize = vi.fn();
    render(
      <TerminalWindow title="Live lane" onMaximize={onMaximize}>
        <p>Exact producer output</p>
      </TerminalWindow>,
    );

    expect(screen.getByRole("button", { name: "Close unavailable" })).toBeDisabled();
    const maximize = screen.getByRole("button", { name: "Maximize window" });
    expect(maximize).toHaveAttribute("aria-pressed", "false");

    await user.click(maximize);
    expect(onMaximize).toHaveBeenLastCalledWith(true);
    expect(screen.getByRole("button", { name: "Restore window" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "Restore window" }));
    expect(onMaximize).toHaveBeenLastCalledWith(false);
  });
});
