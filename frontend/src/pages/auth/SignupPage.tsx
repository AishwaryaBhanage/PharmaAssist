import { useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { useAuth } from '@/auth/AuthProvider';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { FieldError } from '@/components/ui/field-error';
import { describeError, errorCode } from '@/lib/errors';
import { MIN_PASSWORD } from '@/lib/constants';
import { cn } from '@/lib/utils';
import { useDocumentTitle } from '@/lib/useDocumentTitle';
import { AuthLayout } from './AuthLayout';
import { isValidEmail, passwordStrength } from './password';
import { useAfterLogin } from './useAfterLogin';

export function SignupPage() {
  useDocumentTitle('Create account');
  const { signup } = useAuth();
  const afterLogin = useAfterLogin();
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [pending, setPending] = useState(false);
  const [errors, setErrors] = useState<{
    email?: string;
    password?: string;
    name?: string;
    form?: string;
  }>({});
  const strength = passwordStrength(password);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const next: typeof errors = {};
    if (!isValidEmail(email)) next.email = 'Enter a valid email address.';
    if (password.length < MIN_PASSWORD) next.password = `Use at least ${MIN_PASSWORD} characters.`;
    if (displayName.length > 80) next.name = 'Keep the name under 80 characters.';
    setErrors(next);
    if (Object.keys(next).length) return;
    setPending(true);
    try {
      await signup({ email: email.trim(), password, display_name: displayName.trim() });
      afterLogin();
    } catch (err) {
      const code = errorCode(err);
      if (code === 'email_taken')
        setErrors({ email: 'An account with this email already exists.' });
      else if (code === 'weak_password') setErrors({ password: describeError(err).message });
      else if (code === 'signup_disabled')
        setErrors({ form: 'Sign-up is disabled. Ask an administrator to create your account.' });
      else setErrors({ form: describeError(err).message });
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthLayout title="Create account" subtitle="New accounts start with the staff role.">
      <form onSubmit={onSubmit} noValidate className="grid gap-4">
        {errors.form ? (
          <p
            role="alert"
            className="rounded-md bg-danger-bg px-3 py-2 text-sm font-medium text-destructive"
          >
            {errors.form}
          </p>
        ) : null}
        <div className="grid gap-1.5">
          <Label htmlFor="display_name">Name</Label>
          <Input
            id="display_name"
            autoComplete="name"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            maxLength={80}
            aria-invalid={!!errors.name}
          />
          <FieldError message={errors.name} />
        </div>
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
          />
          <FieldError id="email-error" message={errors.email} />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={!!errors.password}
            aria-describedby="password-hint password-error"
            minLength={MIN_PASSWORD}
          />
          <div id="password-hint" className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="flex gap-1" aria-hidden="true">
              {[1, 2, 3].map((n) => (
                <span
                  key={n}
                  className={cn(
                    'h-1 w-6 rounded-full bg-muted',
                    strength.score >= n && (strength.score === 1 ? 'bg-amber' : 'bg-primary'),
                  )}
                />
              ))}
            </span>
            <span>{strength.label || `At least ${MIN_PASSWORD} characters.`}</span>
          </div>
          <FieldError id="password-error" message={errors.password} />
        </div>
        <Button type="submit" loading={pending} className="mt-1 w-full">
          Create account
        </Button>
        <p className="text-center text-sm text-muted-foreground">
          Already have an account?{' '}
          <Link to="/login" className="font-medium text-primary underline-offset-2 hover:underline">
            Sign in
          </Link>
        </p>
      </form>
    </AuthLayout>
  );
}
