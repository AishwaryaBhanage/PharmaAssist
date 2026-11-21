import { Link, NavLink } from 'react-router';
import { ChevronDown, LogOut, Moon, Sun } from 'lucide-react';
import { useAuth } from '@/auth/AuthProvider';
import { useTheme } from '@/lib/theme';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Logo } from './Logo';
import { cn } from '@/lib/utils';
import type { ReactNode } from 'react';

export function TopBar({ leading }: { leading?: ReactNode }) {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const name = user?.display_name?.trim() || user?.email || '';

  return (
    <header className="relative z-30 shrink-0 border-b bg-card">
      <div className="flex h-11 items-center gap-3 px-3 sm:px-4">
        {leading}
        <Link
          to="/"
          className="rounded-md focus-visible:outline-2 focus-visible:outline-ring"
          aria-label="PharmAssist home"
        >
          <Logo />
        </Link>
        <nav className="ml-2 hidden items-center gap-1 sm:flex" aria-label="Primary">
          <TopLink to="/" end>
            Ask
          </TopLink>
          {user?.role === 'admin' ? <TopLink to="/admin">Admin</TopLink> : null}
        </nav>
        <div className="ml-auto flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            onClick={toggle}
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            aria-pressed={theme === 'dark'}
          >
            {theme === 'dark' ? <Sun /> : <Moon />}
          </Button>
          {user ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" className="gap-2 px-2" aria-label="User menu">
                  <span className="max-w-[10rem] truncate text-sm">{name}</span>
                  <Badge
                    variant={user.role === 'admin' ? 'accent' : 'muted'}
                    className="hidden sm:inline-flex"
                  >
                    {user.role}
                  </Badge>
                  <ChevronDown className="opacity-60" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel className="font-normal">
                  <p className="truncate text-sm font-semibold">{name}</p>
                  <p className="truncate text-xs text-muted-foreground">{user.email}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Role: <span className="font-medium text-foreground">{user.role}</span>
                  </p>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={toggle}>
                  {theme === 'dark' ? <Sun /> : <Moon />}
                  {theme === 'dark' ? 'Light theme' : 'Dark theme'}
                </DropdownMenuItem>
                {user.role === 'admin' ? (
                  <DropdownMenuItem asChild>
                    <Link to="/admin">Admin</Link>
                  </DropdownMenuItem>
                ) : null}
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => void logout()}>
                  <LogOut />
                  Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
        </div>
      </div>
    </header>
  );
}

function TopLink({ to, end, children }: { to: string; end?: boolean; children: ReactNode }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          'rounded-md px-2.5 py-1 text-sm font-medium text-muted-foreground hover:bg-secondary hover:text-foreground',
          isActive && 'bg-secondary text-foreground',
        )
      }
    >
      {children}
    </NavLink>
  );
}
