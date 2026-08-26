import { Button, type ButtonProps } from "@heroui/react";

export type SkinButtonProps = ButtonProps;

export function SkinButton({ className = "", ...props }: SkinButtonProps) {
  return (
    <Button
      {...props}
      className={`font-medium tracking-[0.01em] transition-transform duration-[var(--skin-duration-fast)] active:translate-y-px ${className}`}
    />
  );
}

