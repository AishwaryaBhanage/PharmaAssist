import { Link } from 'react-router';
import { ShieldOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useDocumentTitle } from '@/lib/useDocumentTitle';

export function ForbiddenPage() {
  useDocumentTitle('Not allowed');
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
      <ShieldOff className="size-8 text-muted-foreground" aria-hidden="true" />
      <h1 className="text-xl font-semibold">403: admin access required</h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        This area is for administrators. Ask an admin to change your role if you need it.
      </p>
      <Button asChild variant="outline">
        <Link to="/">Back to Ask</Link>
      </Button>
    </main>
  );
}
