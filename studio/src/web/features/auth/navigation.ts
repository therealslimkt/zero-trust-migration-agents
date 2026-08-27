import { containsControlCharacter } from './safety'

export interface AuthReturnState {
  readonly returnTo: string
}
export function readSafeReturnTo(state: unknown, fallback = '/dashboard'): string {
  if (!state || typeof state !== 'object' || !('returnTo' in state)) return fallback
  const returnTo = (state as { returnTo?: unknown }).returnTo
  if (
    typeof returnTo !== 'string' ||
    !returnTo.startsWith('/') ||
    returnTo.startsWith('//') ||
    returnTo.includes('\\') ||
    containsControlCharacter(returnTo)
  ) {
    return fallback
  }
  return returnTo
}
