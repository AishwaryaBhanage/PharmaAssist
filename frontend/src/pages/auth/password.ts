import { MIN_PASSWORD } from '@/lib/constants';

export type Strength = { score: 0 | 1 | 2 | 3; label: string };

/** A simple strength hint: length and character variety. Not a security control. */
export function passwordStrength(pw: string): Strength {
  if (!pw) return { score: 0, label: '' };
  let variety = 0;
  if (/[a-z]/.test(pw)) variety++;
  if (/[A-Z]/.test(pw)) variety++;
  if (/\d/.test(pw)) variety++;
  if (/[^A-Za-z0-9]/.test(pw)) variety++;
  if (pw.length < MIN_PASSWORD)
    return { score: 1, label: `Too short (minimum ${MIN_PASSWORD} characters)` };
  if (pw.length >= 14 && variety >= 3) return { score: 3, label: 'Strong' };
  if (pw.length >= 12 || variety >= 3) return { score: 2, label: 'Good' };
  return { score: 1, label: 'Weak: add length or mix letters, numbers and symbols' };
}

export function isValidEmail(v: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim());
}
