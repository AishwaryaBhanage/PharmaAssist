import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import type { Options as SanitizeOptions } from 'rehype-sanitize';
import type { AnchorHTMLAttributes } from 'react';

/**
 * Strict schema: no raw HTML survives (react-markdown already does not parse it; the sanitizer is a
 * second fence), only text-level tags, lists, tables and links. Links may be http(s) or relative
 * `/api/v1/...` paths. Images are not allowed.
 */
export const ANSWER_SCHEMA: SanitizeOptions = {
  ...defaultSchema,
  tagNames: [
    'p',
    'br',
    'strong',
    'em',
    'b',
    'i',
    'code',
    'pre',
    'del',
    'ul',
    'ol',
    'li',
    'h1',
    'h2',
    'h3',
    'h4',
    'table',
    'thead',
    'tbody',
    'tr',
    'th',
    'td',
    'blockquote',
    'hr',
    'a',
  ],
  attributes: {
    a: ['href'],
    ol: ['start'],
    th: ['align'],
    td: ['align'],
    code: [['className', /^language-./]],
  },
  protocols: { href: ['http', 'https'] },
  clobberPrefix: '',
  clobber: [],
  strip: ['script', 'style', 'iframe', 'object', 'embed', 'img', 'svg', 'math'],
};

const LOCAL_LINK = /^\/api\/v1\/[A-Za-z0-9_\-./%#=?]+$/;

export function isAllowedHref(href: string | undefined): href is string {
  if (!href) return false;
  if (LOCAL_LINK.test(href)) return true;
  try {
    const u = new URL(href);
    return u.protocol === 'http:' || u.protocol === 'https:';
  } catch {
    return false;
  }
}

function SafeLink({ href, children, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement>) {
  if (!isAllowedHref(href)) return <span>{children}</span>;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>
      {children}
    </a>
  );
}

const COMPONENTS = { a: SafeLink } as const;

export function AnswerMarkdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={className}>
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeSanitize, ANSWER_SCHEMA]]}
        skipHtml
        components={COMPONENTS}
      >
        {children}
      </Markdown>
    </div>
  );
}
