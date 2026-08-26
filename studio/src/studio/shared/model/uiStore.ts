import { create } from "zustand";

export type SkinTheme = "skin-day" | "skin-night";
export type StudioDensity = "comfortable" | "compact";

interface UiState {
  theme: SkinTheme;
  density: StudioDensity;
  sidebarCollapsed: boolean;
  streamPaused: boolean;
  setTheme(theme: SkinTheme): void;
  toggleDensity(): void;
  toggleSidebar(): void;
  toggleStream(): void;
}

export const useUiStore = create<UiState>((set) => ({
  theme: "skin-day",
  density: "comfortable",
  sidebarCollapsed: false,
  streamPaused: false,
  setTheme: (theme) => {
    document.documentElement.dataset.theme = theme;
    set({ theme });
  },
  toggleDensity: () => set((state) => ({ density: state.density === "comfortable" ? "compact" : "comfortable" })),
  toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
  toggleStream: () => set((state) => ({ streamPaused: !state.streamPaused })),
}));

