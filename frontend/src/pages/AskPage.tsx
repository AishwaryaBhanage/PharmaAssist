import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { PanelLeft, Sparkles } from 'lucide-react';
import type { FeedbackIn } from '@/api/types';
import { useAsk, useConversation, useFeedback, useReadiness } from '@/api/queries';
import { TopBar } from '@/components/layout/TopBar';
import { ReadinessBanner } from '@/components/layout/ReadinessBanner';
import { ConversationSidebar } from '@/components/ask/ConversationSidebar';
import { Composer, ExampleQuestions } from '@/components/ask/Composer';
import { Thread, AnswerSkeleton } from '@/components/ask/Thread';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { useErrorToast } from '@/lib/errors';
import { useDocumentTitle } from '@/lib/useDocumentTitle';
import { cn } from '@/lib/utils';

export function AskPage() {
  const { conversationId = null } = useParams<{ conversationId: string }>();
  const navigate = useNavigate();
  const toastError = useErrorToast();
  const readiness = useReadiness();
  const ready = !!readiness.data?.ready;

  const conversation = useConversation(conversationId);
  const askMutation = useAsk();
  const feedback = useFeedback(conversationId ?? askMutation.data?.conversation_id ?? '');

  const [draft, setDraft] = useState('');
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [feedbackPendingId, setFeedbackPendingId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useDocumentTitle(conversation.data?.title ? conversation.data.title : 'Ask');

  // A deleted or missing conversation falls back to a fresh question.
  useEffect(() => {
    if (conversation.isError) navigate('/', { replace: true });
  }, [conversation.isError, navigate]);

  function submit() {
    const question = draft.trim();
    if (!question || askMutation.isPending) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setPendingQuestion(question);
    askMutation.mutate(
      { body: { question, conversation_id: conversationId }, signal: controller.signal },
      {
        onSuccess: (answer) => {
          setDraft('');
          setPendingQuestion(null);
          if (answer.conversation_id !== conversationId) {
            navigate(`/c/${encodeURIComponent(answer.conversation_id)}`);
          }
        },
        onError: (e) => {
          setPendingQuestion(null);
          if (e instanceof DOMException && e.name === 'AbortError') return;
          toastError(e, 'The question could not be answered');
        },
        onSettled: () => {
          abortRef.current = null;
        },
      },
    );
  }

  function cancel() {
    abortRef.current?.abort();
    abortRef.current = null;
    setPendingQuestion(null);
    askMutation.reset();
  }

  function sendFeedback(messageId: string, body: FeedbackIn) {
    setFeedbackPendingId(messageId);
    feedback.mutate(
      { messageId, body },
      {
        onError: (e) => toastError(e, 'Feedback could not be saved'),
        onSettled: () => setFeedbackPendingId(null),
      },
    );
  }

  const messages = conversation.data?.messages ?? [];
  const showEmpty = !conversationId && !pendingQuestion;

  const sidebar = (
    <ConversationSidebar
      selectedId={conversationId}
      onSelect={() => setSidebarOpen(false)}
      onNew={() => {
        setSidebarOpen(false);
        setDraft('');
        navigate('/');
      }}
      onDeleted={(id) => {
        if (id === conversationId) navigate('/');
      }}
    />
  );

  // Fixed app shell: the viewport is the frame, only the thread column (and the
  // conversation list in the sidebar) scroll; top bar, banner and composer stay put.
  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <TopBar
        leading={
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            aria-label="Open conversations"
            onClick={() => setSidebarOpen(true)}
          >
            <PanelLeft />
          </Button>
        }
      />
      <ReadinessBanner />
      <div className="flex min-h-0 flex-1">
        <aside
          className="hidden w-72 shrink-0 flex-col border-r bg-card md:flex"
          aria-label="Conversations"
        >
          {sidebar}
        </aside>
        <Sheet open={sidebarOpen} onOpenChange={setSidebarOpen}>
          <SheetContent side="left" className="w-80 gap-0 p-0 pt-9 sm:max-w-sm">
            <SheetTitle className="sr-only">Conversations</SheetTitle>
            {sidebar}
          </SheetContent>
        </Sheet>

        <main className="flex min-w-0 flex-1 flex-col bg-background">
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain">
            <div
              className={cn(
                'mx-auto flex w-full max-w-3xl grow flex-col px-4 py-6 sm:px-6',
                showEmpty && 'items-center justify-center',
              )}
            >
              {showEmpty ? (
                <Welcome
                  onPick={(q) => {
                    setDraft(q);
                    document.getElementById('question')?.focus();
                  }}
                />
              ) : conversationId && conversation.isPending ? (
                <div className="grid gap-6" aria-busy="true">
                  <AnswerSkeleton />
                  <AnswerSkeleton />
                </div>
              ) : (
                <Thread
                  messages={messages}
                  pendingQuestion={pendingQuestion}
                  onFeedback={sendFeedback}
                  feedbackPendingId={feedbackPendingId}
                />
              )}
            </div>
          </div>
          <div className="shrink-0 border-t bg-card/80 backdrop-blur supports-[backdrop-filter]:bg-card/70">
            <div className="mx-auto w-full max-w-3xl px-4 py-4 sm:px-6">
              <Composer
                value={draft}
                onChange={setDraft}
                onSubmit={submit}
                onCancel={cancel}
                pending={askMutation.isPending}
                ready={ready}
              />
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

/** The first-run card: what the assistant does, plus example questions to click. */
function Welcome({ onPick }: { onPick: (q: string) => void }) {
  return (
    <section
      className="w-full max-w-2xl rounded-2xl border bg-card px-6 py-10 text-center shadow-xs sm:px-10"
      aria-labelledby="welcome-heading"
    >
      <div className="mx-auto mb-5 flex size-14 items-center justify-center rounded-full bg-accent text-accent-foreground ring-8 ring-accent/40">
        <Sparkles className="size-6" aria-hidden="true" />
      </div>
      <h1 id="welcome-heading" className="text-2xl font-semibold tracking-tight">
        Ask a policy or formulary question
      </h1>
      <p className="mx-auto mt-2 max-w-md text-[15px] leading-relaxed text-muted-foreground">
        One question in, one cited answer out. If the program is not stated the assistant infers it
        and says so at the top of the answer.
      </p>
      <p className="mb-3 mt-8 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        Try one of these
      </p>
      <ExampleQuestions className="justify-center" onPick={onPick} />
    </section>
  );
}
