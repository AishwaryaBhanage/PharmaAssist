import { useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { useAuth } from '@/auth/AuthProvider';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { FieldError } from '@/components/ui/field-error';
import { describeError, errorCode } from '@/lib/errors';
import { useDocumentTitle } from '@/lib/useDocumentTitle';
import { AuthLayout } from './AuthLayout';
import { isValidEmail } from './password';
import { useAfterLogin } from './useAfterLogin';

export function LoginPage() {
  useDocumentTitle('Sign in');
  const { login, lostReason } = useAuth();
  const afterLogin = useAfterLogin();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [pending, setPending] = useState(false);
  const [errors, setErrors] = useState<{ email?: string; password?: string; form?: string }>({});

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const next: typeof errors = {};
    if (!isValidEmail(email)) next.email = 'Enter a valid email address.';
    if (!password) next.password = 'Enter your password.';
    setErrors(next);
    if (Object.keys(next).length) return;
    setPending(true);
    try {
      await login({ email: email.trim(), password });
      afterLogin();
    } catch (err) {
      const code = errorCode(err);
      if (code === 'invalid_credentials') {
        setErrors({ form: 'Email or password is incorrect.' });
      } else if (code === 'forbidden') {
        setErrors({ form: 'This account is deactivated. Contact an administrator.' });
      } else {
        setErrors({ form: describeError(err).message });
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthLayout title="Sign in" subtitle="Pharmacy policy and formulary answers, with citations.">
      <form onSubmit={onSubmit} noValidate className="grid gap-4">
        {lostReason === 'expired' && !errors.form ? (
          <p role="status" className="rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
            Your session expired. Sign in again to continue.
          </p>
        ) : null}
        {errors.form ? (
          <p
            role="alert"
            className="rounded-md bg-danger-bg px-3 py-2 text-sm font-medium text-destructive"
          >
            {errors.form}
          </p>
        ) : null}
        <div className="grid gap-1.5">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={!!errors.email}
            aria-describedby={errors.email ? 'email-error' : undefined}
            autoFocus
          />
          <FieldError id="email-error" message={errors.email} />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={!!errors.password}
            aria-describedby={errors.password ? 'password-error' : undefined}
          />
          <FieldError id="password-error" message={errors.password} />
        </div>
        <Button type="submit" loading={pending} className="mt-1 w-full">
          Sign in
        </Button>
        {import.meta.env.VITE_MOCK === '1' ? (
          <p className="rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground">
            Mock mode. Admin: admin@pharmassist.local / admin-password-1. Staff:
            dana@pharmassist.local / staff-password-1.
          </p>
        ) : null}
        <p className="text-center text-sm text-muted-foreground">
          New here?{' '}
          <Link
            to="/signup"
            className="font-medium text-primary underline-offset-2 hover:underline"
          >
            Create an account
          </Link>
        </p>
      </form>
    </AuthLayout>
  );
}
