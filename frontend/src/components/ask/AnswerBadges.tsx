import { Database, ShieldAlert, Shuffle } from 'lucide-react';
import type { AnswerOut } from '@/api/types';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

/** Cached / Fallback model / Needs review badges, shared by the staff answer card and the admin drawer. */
export function AnswerBadges({ answer }: { answer: AnswerOut }) {
  const sim =
    typeof answer.cache_similarity === 'number' ? answer.cache_similarity.toFixed(2) : null;
  return (
    <>
      {answer.cached ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge
              variant="amber"
              tabIndex={0}
              aria-describedby={`cached-tip-${answer.message_id}`}
            >
              <Database aria-hidden="true" />
              Cached
            </Badge>
          </TooltipTrigger>
          <TooltipContent id={`cached-tip-${answer.message_id}`}>
            Matched: {answer.matched_question || 'a previous question'}
            {sim ? ` (similarity ${sim})` : ''}
          </TooltipContent>
        </Tooltip>
      ) : null}
      {answer.fallback_used ? (
        <Badge variant="outline">
          <Shuffle aria-hidden="true" />
          Fallback model
        </Badge>
      ) : null}
      {answer.needs_review && answer.status === 'answered' ? (
        <Badge variant="amber">
          <ShieldAlert aria-hidden="true" />
          Needs pharmacist review
        </Badge>
      ) : null}
    </>
  );
}
