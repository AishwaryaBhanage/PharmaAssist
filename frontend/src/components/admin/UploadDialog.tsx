import { useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { FileUp, X } from 'lucide-react';
import type { UploadFields, UploadOut } from '@/api/types';
import { uploadDocument } from '@/api/endpoints';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { FieldError } from '@/components/ui/field-error';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useToast } from '@/components/ui/toast';
import { AUTHORITIES, DOC_TYPES, MAX_UPLOAD_BYTES, PROGRAMS } from '@/lib/constants';
import { describeError, errorCode } from '@/lib/errors';
import { formatBytes, slugify } from '@/lib/format';
import { cn } from '@/lib/utils';

const ACCEPT = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
];
const ACCEPT_EXT = ['.pdf', '.xlsx'];

export function validateFile(file: File): string | null {
  const ext = file.name.toLowerCase().slice(file.name.lastIndexOf('.'));
  if (!ACCEPT.includes(file.type) && !ACCEPT_EXT.includes(ext))
    return 'Only PDF and XLSX files are accepted.';
  if (file.size > MAX_UPLOAD_BYTES) return `File is ${formatBytes(file.size)}; the limit is 50 MB.`;
  if (file.size === 0) return 'The file is empty.';
  return null;
}

type Errors = Partial<Record<keyof UploadFields | 'file' | 'form', string>>;

export function validateFields(f: UploadFields): Errors {
  const e: Errors = {};
  if (!f.title.trim()) e.title = 'Title is required.';
  if (!/^[a-z0-9][a-z0-9_]{1,63}$/.test(f.doc_id))
    e.doc_id = 'Use 2–64 lowercase letters, digits or underscores.';
  if (!f.program) e.program = 'Choose a program.';
  if (!f.authority) e.authority = 'Choose binding or advisory.';
  if (!f.doc_type) e.doc_type = 'Choose a document type.';
  if (!f.publisher.trim()) e.publisher = 'Publisher is required.';
  if (!/^\d{4}-\d{2}-\d{2}$/.test(f.doc_date)) e.doc_date = 'Enter the document date.';
  if (f.source_url && !/^https?:\/\//.test(f.source_url))
    e.source_url = 'Must start with http:// or https://';
  return e;
}

const EMPTY: UploadFields = {
  doc_id: '',
  title: '',
  program: '',
  doc_type: '',
  authority: '',
  publisher: '',
  doc_date: '',
  source_url: '',
};

export function UploadDialog({
  open,
  onOpenChange,
  onUploaded,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onUploaded?: (r: UploadOut) => void;
}) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [fields, setFields] = useState<UploadFields>(EMPTY);
  const [slugEdited, setSlugEdited] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const [progress, setProgress] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) {
      setFile(null);
      setFields(EMPTY);
      setSlugEdited(false);
      setErrors({});
      setProgress(null);
      abortRef.current?.abort();
      abortRef.current = null;
    }
  }, [open]);

  function set<K extends keyof UploadFields>(k: K, v: UploadFields[K]) {
    setFields((f) => {
      const next = { ...f, [k]: v };
      if (k === 'title' && !slugEdited) next.doc_id = slugify(v);
      return next;
    });
    setErrors((e) => ({ ...e, [k]: undefined, form: undefined }));
  }

  function pick(f: File | null) {
    if (!f) return;
    const err = validateFile(f);
    setErrors((e) => ({ ...e, file: err ?? undefined, form: undefined }));
    setFile(err ? null : f);
    if (!err && !fields.title) {
      const base = f.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ');
      set('title', base);
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    pick(e.dataTransfer.files[0] ?? null);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs = validateFields(fields);
    if (!file) errs.file = 'Choose a PDF or XLSX file.';
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setProgress(0);
    try {
      const result = await uploadDocument(file!, fields, setProgress, controller.signal);
      void qc.invalidateQueries({ queryKey: ['admin', 'documents'] });
      void qc.invalidateQueries({ queryKey: ['admin', 'jobs'] });
      toast({
        kind: 'success',
        title: result.reused ? 'Identical file already indexed' : 'Upload queued',
        description: result.reused
          ? `${result.document.title} already has this exact file as its active version.`
          : `${result.document.title} is queued for indexing; follow it in the jobs panel.`,
      });
      onUploaded?.(result);
      onOpenChange(false);
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      const code = errorCode(err);
      const msg = describeError(err).message;
      if (code === 'upload_too_large' || code === 'upload_type' || code === 'upload_pages')
        setErrors({ file: msg });
      else if (code === 'duplicate_version') setErrors({ form: msg });
      else if (code === 'validation_error') setErrors({ form: msg });
      else setErrors({ form: msg });
    } finally {
      setProgress(null);
      abortRef.current = null;
    }
  }

  const uploading = progress !== null;

  return (
    <Dialog open={open} onOpenChange={(o) => !uploading && onOpenChange(o)}>
      <DialogContent
        className="max-w-xl"
        onInteractOutside={(e) => uploading && e.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>Upload a document</DialogTitle>
          <DialogDescription>
            PDF or XLSX up to 50 MB. A new version is indexed in the background and becomes
            searchable when it is verified.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={cn(
              'flex flex-col items-center justify-center gap-2 rounded-md border-2 border-dashed p-5 text-center text-sm',
              dragging && 'border-primary bg-accent/50',
              errors.file && 'border-destructive',
            )}
          >
            <FileUp className="size-5 text-muted-foreground" aria-hidden="true" />
            {file ? (
              <p className="flex items-center gap-2">
                <span className="font-medium">{file.name}</span>
                <span className="text-muted-foreground">{formatBytes(file.size)}</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Remove file"
                  onClick={() => setFile(null)}
                  disabled={uploading}
                >
                  <X />
                </Button>
              </p>
            ) : (
              <p className="text-muted-foreground">Drag a file here, or</p>
            )}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => inputRef.current?.click()}
              disabled={uploading}
            >
              {file ? 'Choose another file' : 'Choose a file'}
            </Button>
            <input
              ref={inputRef}
              type="file"
              accept=".pdf,.xlsx,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              className="sr-only"
              aria-label="Document file"
              onChange={(e) => pick(e.target.files?.[0] ?? null)}
            />
            <FieldError message={errors.file} />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="u-title" label="Title" error={errors.title} className="sm:col-span-2">
              <Input
                id="u-title"
                value={fields.title}
                onChange={(e) => set('title', e.target.value)}
                aria-invalid={!!errors.title}
              />
            </Field>
            <Field
              id="u-slug"
              label="Document id (slug)"
              error={errors.doc_id}
              hint="Suggested from the title; existing ids add a new version."
            >
              <Input
                id="u-slug"
                value={fields.doc_id}
                onChange={(e) => {
                  setSlugEdited(true);
                  set('doc_id', e.target.value.toLowerCase());
                }}
                aria-invalid={!!errors.doc_id}
                className="font-mono text-xs"
              />
            </Field>
            <Field id="u-program" label="Program" error={errors.program}>
              <Select value={fields.program} onValueChange={(v) => set('program', v)}>
                <SelectTrigger id="u-program" aria-invalid={!!errors.program}>
                  <SelectValue placeholder="Select a program" />
                </SelectTrigger>
                <SelectContent>
                  {PROGRAMS.map((p) => (
                    <SelectItem key={p} value={p}>
                      {p}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field id="u-authority" label="Authority" error={errors.authority}>
              <Select value={fields.authority} onValueChange={(v) => set('authority', v)}>
                <SelectTrigger id="u-authority" aria-invalid={!!errors.authority}>
                  <SelectValue placeholder="binding or advisory" />
                </SelectTrigger>
                <SelectContent>
                  {AUTHORITIES.map((a) => (
                    <SelectItem key={a} value={a}>
                      {a}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field id="u-type" label="Document type" error={errors.doc_type}>
              <Select value={fields.doc_type} onValueChange={(v) => set('doc_type', v)}>
                <SelectTrigger id="u-type" aria-invalid={!!errors.doc_type}>
                  <SelectValue placeholder="Select a type" />
                </SelectTrigger>
                <SelectContent>
                  {DOC_TYPES.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field id="u-publisher" label="Publisher" error={errors.publisher}>
              <Input
                id="u-publisher"
                value={fields.publisher}
                onChange={(e) => set('publisher', e.target.value)}
                aria-invalid={!!errors.publisher}
              />
            </Field>
            <Field id="u-date" label="Document date" error={errors.doc_date}>
              <Input
                id="u-date"
                type="date"
                value={fields.doc_date}
                onChange={(e) => set('doc_date', e.target.value)}
                aria-invalid={!!errors.doc_date}
              />
            </Field>
            <Field
              id="u-url"
              label="Source URL (optional)"
              error={errors.source_url}
              className="sm:col-span-2"
            >
              <Input
                id="u-url"
                type="url"
                value={fields.source_url}
                onChange={(e) => set('source_url', e.target.value)}
                aria-invalid={!!errors.source_url}
                placeholder="https://"
              />
            </Field>
          </div>

          {uploading ? (
            <div className="grid gap-1" aria-live="polite">
              <Progress value={Math.round((progress ?? 0) * 100)} aria-label="Upload progress" />
              <p className="text-xs text-muted-foreground">
                {progress !== null && progress >= 1
                  ? 'Processing…'
                  : `Uploading ${Math.round((progress ?? 0) * 100)}%`}
              </p>
            </div>
          ) : null}
          <FieldError message={errors.form} />

          <DialogFooter>
            {uploading ? (
              <Button type="button" variant="outline" onClick={() => abortRef.current?.abort()}>
                Cancel upload
              </Button>
            ) : (
              <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
            )}
            <Button type="submit" loading={uploading}>
              Upload and index
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  id,
  label,
  error,
  hint,
  className,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn('grid gap-1.5', className)}>
      <Label htmlFor={id}>{label}</Label>
      {children}
      {hint && !error ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      <FieldError message={error} />
    </div>
  );
}
