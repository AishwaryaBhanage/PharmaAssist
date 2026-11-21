import { render } from '@testing-library/react';
import { AnswerMarkdown, isAllowedHref } from '@/lib/markdown';

describe('AnswerMarkdown sanitization', () => {
  it('strips raw HTML, scripts, images and event handlers', () => {
    const md = [
      '<script>window.pwned = 1</script>',
      '<img src="x" onerror="window.pwned = 1">',
      '<iframe src="https://evil.example"></iframe>',
      '<b onclick="window.pwned = 1">raw bold</b>',
      '',
      'Plain **bold** and `code`.',
    ].join('\n');
    const { container } = render(<AnswerMarkdown>{md}</AnswerMarkdown>);
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('iframe')).toBeNull();
    expect(container.querySelector('[onclick]')).toBeNull();
    expect(container.querySelector('[onerror]')).toBeNull();
    expect(container.querySelector('strong')).toHaveTextContent('bold');
    expect(container.querySelector('code')).toHaveTextContent('code');
    expect(container.textContent).not.toContain('raw bold');
  });

  it('keeps http(s) and /api/v1 links, drops javascript: and other schemes', () => {
    const md = [
      '[good](https://example.com/page)',
      '[local](/api/v1/sources/doc/p3.pdf)',
      '[bad](javascript:alert(1))',
      '[data](data:text/html,hi)',
      '[relative](../etc/passwd)',
    ].join(' ');
    const { container } = render(<AnswerMarkdown>{md}</AnswerMarkdown>);
    const hrefs = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href'));
    expect(hrefs).toEqual(['https://example.com/page', '/api/v1/sources/doc/p3.pdf']);
    for (const a of container.querySelectorAll('a')) {
      expect(a).toHaveAttribute('target', '_blank');
      expect(a.getAttribute('rel')).toContain('noopener');
    }
    expect(container.textContent).toContain('bad');
    expect(container.textContent).toContain('relative');
  });

  it('renders GFM tables and numbered steps', () => {
    const md = '| A | B |\n|---|---|\n| 1 | 2 |\n\n1. first\n2. second';
    const { container } = render(<AnswerMarkdown>{md}</AnswerMarkdown>);
    expect(container.querySelector('table')).not.toBeNull();
    expect(container.querySelectorAll('ol li')).toHaveLength(2);
  });

  it('isAllowedHref accepts only http(s) and /api/v1 paths', () => {
    expect(isAllowedHref('https://a.b/c')).toBe(true);
    expect(isAllowedHref('http://a.b')).toBe(true);
    expect(isAllowedHref('/api/v1/figures/x/p001_f1.png')).toBe(true);
    expect(isAllowedHref('/static/x.png')).toBe(false);
    expect(isAllowedHref('javascript:alert(1)')).toBe(false);
    expect(isAllowedHref(undefined)).toBe(false);
  });
});
