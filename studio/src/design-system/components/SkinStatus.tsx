import { Chip } from "@heroui/react";

export type SkinStatusTone = "neutral" | "info" | "success" | "warning" | "danger";

export interface SkinStatusProps {
  label: string;
  tone?: SkinStatusTone;
}

const colorByTone = {
  neutral: "default",
  info: "accent",
  success: "success",
  warning: "warning",
  danger: "danger",
} as const;

export function SkinStatus({ label, tone = "neutral" }: SkinStatusProps) {
  return (
    <Chip color={colorByTone[tone]} variant="soft" size="sm">
      {label}
    </Chip>
  );
}

