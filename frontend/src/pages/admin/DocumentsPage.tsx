import { useMemo, useState } from 'react';
import { ExternalLink, FileUp, RefreshCw, Trash2 } from 'lucide-react';
import type { DocumentOut, JobOut, VersionOut } from '@/api/types';
import {
  isLiveJob,
  useAdminDocuments,
  useAdminJobs,
  useReindex,
  useRemoveFromIndex,
} from '@/api/queries';
import { JobsPanel } from '@/components/admin/JobsPanel';
import { UploadDialog } from '@/components/admin/UploadDialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useToast } from '@/components/ui/toast';
import { useErrorToast } from '@/lib/errors';
import { formatDate, formatInt } from '@/lib/format';
import { useDocumentTitle } from '@/lib/useDocumentTitle';
import { cn } from '@/lib/utils';
import { PageHeader } from './AdminLayout';

type DocState = 'indexing' | 'active' | 'failed' | 'not_indexed';

/** What the Status column says about a document, given its versions and any live job. */
export function documentState(d: DocumentOut, liveJob: boolean): DocState {
  if (liveJob) return 'indexing';
  if (d.active_version?.status === 'active') return 'active';
  if (d.latest_version?.status === 'failed') return 'failed';
  return 'not_indexed';
}

export function DocumentsPage() {
  useDocumentTitle('Admin · Documents');
  const docs = useAdminDocuments();
  const jobs = useAdminJobs({ limit: 10 });
  const reindex = useReindex();
  const removeIndex = useRemoveFromIndex();
  const { toast } = useToast();
  const toastError = useErrorToast();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [reindexDoc, setReindexDoc] = useState<DocumentOut | null>(null);
  const [removeDoc, setRemoveDoc] = useState<DocumentOut | null>(null);

  const titles = useMemo(
    () => Object.fromEntries((docs.data ?? []).map((d) => [d.id, d.title])),
    [docs.data],
  );
  const busyDocs = useMemo(() => {
    const s = new Set<string>();
    const items: JobOut[] = jobs.data?.items ?? [];
    for (const j of items) if (isLiveJob(j.status, j.stage)) s.add(j.document_id);
    return s;
  }, [jobs.data]);

  return (
    <>
      <PageHeader
        title="Documents"
        description="Sources the assistant may cite. Only the active version of each document is searchable."
      />

      <div className="grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)] gap-4">
        {/* Top band: upload on the left, recent indexing jobs beside it. */}
        <div className="flex min-w-0 flex-col gap-4 lg:flex-row">
          <section
            className="flex shrink-0 flex-col justify-between gap-3 rounded-lg border bg-card p-4 shadow-xs lg:w-64"
            aria-labelledby="upload-heading"
          >
            <div className="flex items-start gap-3">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-accent text-accent-foreground">
                <FileUp className="size-4" aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <h2 id="upload-heading" className="text-sm font-semibold">
                  Add a document
                </h2>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  PDF or XLSX up to 50 MB. A new version is indexed in the background and becomes
                  searchable once verified.
                </p>
              </div>
            </div>
            <Button className="w-full" onClick={() => setUploadOpen(true)}>
              <FileUp />
              Upload
            </Button>
          </section>
          <JobsPanel documentTitles={titles} className="min-h-0 flex-1" />
        </div>

        {/* Bottom: the documents table, full width, scrolling inside its card. */}
        <div className="flex min-h-0 flex-col overflow-hidden rounded-lg border bg-card shadow-xs">
          {docs.isPending ? (
            <div className="grid gap-2 p-3" aria-busy="true">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-9 w-full" />
              ))}
            </div>
          ) : docs.isError ? (
            <p role="alert" className="p-4 text-sm text-destructive">
              Could not load documents.
            </p>
          ) : !docs.data.length ? (
            <EmptyState
              title="No documents yet"
              description="Upload a PDF or XLSX to start answering questions."
              className="m-3"
            />
          ) : (
            <Table containerClassName="min-h-0 flex-1">
              <TableHeader className="sticky top-0 z-10 shadow-[inset_0_-1px_0_var(--border)]">
                <TableRow className="border-0 hover:bg-transparent">
                  <TableHead>Title</TableHead>
                  <TableHead>Program</TableHead>
                  <TableHead>Authority</TableHead>
                  <TableHead>Date</TableHead>
                  <TableHead>Version</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {docs.data.map((d) => {
                  const busy = busyDocs.has(d.id);
                  const st = documentState(d, busy);
                  const actionsLocked = busy || reindex.isPending || removeIndex.isPending;
                  return (
                    <TableRow key={d.id} data-testid={`doc-row-${d.id}`}>
                      <TableCell className="min-w-[14rem] max-w-[20rem]">
                        <div className="font-medium leading-snug">{d.title}</div>
                        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                          <span className="font-mono">{d.id}</span>
                          <span>· {d.doc_type}</span>
                          {d.source_url ? (
                            <a
                              href={d.source_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-0.5 hover:underline"
                              aria-label={`Open the publisher's page for ${d.title}`}
                            >
                              {d.publisher}
                              <ExternalLink className="size-3" aria-hidden="true" />
                            </a>
                          ) : (
                            <span>{d.publisher}</span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="whitespace-nowrap">{d.program}</TableCell>
                      <TableCell>
                        <Badge variant={d.authority === 'binding' ? 'accent' : 'outline'}>
                          {d.authority}
                        </Badge>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs">
                        {formatDate(d.doc_date)}
                      </TableCell>
                      <TableCell className="min-w-[11rem]">
                        <VersionCell doc={d} />
                      </TableCell>
                      <TableCell>
                        <DocStatusBadge state={st} error={d.latest_version?.error} />
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex flex-col items-end gap-0.5">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setReindexDoc(d)}
                            disabled={actionsLocked}
                            aria-label={`Re-index ${d.title}`}
                            title={
                              busy ? 'An indexing job for this document is running' : undefined
                            }
                          >
                            <RefreshCw />
                            Re-index
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-destructive hover:bg-danger-bg hover:text-destructive"
                            onClick={() => setRemoveDoc(d)}
                            disabled={actionsLocked || st !== 'active'}
                            aria-label={`Remove ${d.title} from the index`}
                            title={
                              busy
                                ? 'An indexing job for this document is running'
                                : st !== 'active'
                                  ? 'Nothing is indexed for this document'
                                  : undefined
                            }
                          >
                            <Trash2 />
                            Remove from index
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </div>
      </div>

      <UploadDialog open={uploadOpen} onOpenChange={setUploadOpen} />

      <ConfirmDialog
        open={!!reindexDoc}
        onOpenChange={(o) => !o && setReindexDoc(null)}
        title={`Re-index ${reindexDoc?.title ?? ''}?`}
        description={
          reindexDoc?.active_version
            ? 'The active file is parsed, chunked and embedded again with the current pipeline. The current version stays searchable until the new one is verified.'
            : 'The stored file of the latest version is parsed, chunked and embedded again with the current pipeline. The document becomes searchable once the new version is verified.'
        }
        confirmLabel="Re-index"
        pending={reindex.isPending}
        onConfirm={() => {
          if (!reindexDoc) return;
          reindex.mutate(reindexDoc.id, {
            onSuccess: () => {
              setReindexDoc(null);
              toast({ kind: 'success', title: 'Re-index queued', description: reindexDoc.title });
            },
            onError: (e) => toastError(e, 'Could not queue the re-index'),
          });
        }}
      />

      <ConfirmDialog
        open={!!removeDoc}
        onOpenChange={(o) => !o && setRemoveDoc(null)}
        title={`Remove ${removeDoc?.title ?? ''} from the index?`}
        description="Its chunks, embeddings, figures and table rows are deleted and the assistant stops citing it. The uploaded file stays, so you can re-index it later."
        confirmLabel="Remove from index"
        destructive
        pending={removeIndex.isPending}
        onConfirm={() => {
          if (!removeDoc) return;
          const title = removeDoc.title;
          removeIndex.mutate(removeDoc.id, {
            onSuccess: (r) => {
              setRemoveDoc(null);
              toast({
                kind: 'success',
                title: `${title} removed from the index (${formatInt(r.removed.chunks)} chunks)`,
                description: 'The uploaded file is kept; use Re-index to make it searchable again.',
              });
            },
            onError: (e) => {
              setRemoveDoc(null);
              toastError(e, 'Could not remove the document from the index');
            },
          });
        }}
      />
    </>
  );
}

function shortId(id: string): string {
  return id.slice(0, 8);
}

/** Active version details, or the latest version's file when nothing is indexed. */
function VersionCell({ doc: d }: { doc: DocumentOut }) {
  const v: VersionOut | null | undefined = d.active_version ?? d.latest_version;
  if (!v) return <span className="text-xs text-muted-foreground">No file uploaded</span>;
  const isActive = !!d.active_version;
  const counts = [
    v.pages != null ? `${formatInt(v.pages)} pages` : null,
    isActive ? `${formatInt(v.chunk_count)} chunks` : null,
    isActive && v.figure_count ? `${formatInt(v.figure_count)} figures` : null,
  ].filter(Boolean);
  const newer =
    isActive && d.latest_version && d.latest_version.id !== d.active_version?.id
      ? d.latest_version
      : null;
  return (
    <div className="grid gap-0.5 text-xs">
      <span className="max-w-[13rem] truncate font-medium text-foreground" title={v.file_name}>
        {v.file_name}
      </span>
      <span className="text-muted-foreground">
        <span className="font-mono" title={v.id}>
          {shortId(v.id)}
        </span>
        {isActive && v.activated_at ? ` · activated ${formatDate(v.activated_at)}` : null}
        {!isActive && v.created_at ? ` · uploaded ${formatDate(v.created_at)}` : null}
      </span>
      {counts.length ? (
        <span className="tabular-nums text-muted-foreground">{counts.join(' · ')}</span>
      ) : null}
      {newer ? (
        <span
          className={cn(
            'max-w-[13rem] truncate',
            newer.status === 'failed' ? 'text-destructive' : 'text-muted-foreground',
          )}
          title={newer.error ?? undefined}
        >
          Newer version {shortId(newer.id)}:{' '}
          {newer.status === 'failed'
            ? `failed${newer.error ? ` – ${newer.error}` : ''}`
            : newer.status}
        </span>
      ) : null}
    </div>
  );
}

function DocStatusBadge({ state, error }: { state: DocState; error?: string | null }) {
  if (state === 'indexing')
    return (
      <Badge variant="amber">
        <span aria-hidden="true" className="size-1.5 animate-pulse rounded-full bg-current" />
        Indexing…
      </Badge>
    );
  if (state === 'active') return <Badge variant="success">Active</Badge>;
  if (state === 'failed')
    return (
      <Badge variant="destructive" className="max-w-[14rem]" title={error ?? undefined}>
        <span className="truncate">Failed{error ? `: ${error}` : ''}</span>
      </Badge>
    );
  return <Badge variant="muted">Not indexed</Badge>;
}
