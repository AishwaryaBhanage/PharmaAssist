# Requirements

The product requirements for the assistant. Design choices in [`writeup/DESIGN.md`](writeup/DESIGN.md) trace back to these.

## Interaction
- **Single window:** one question in, one answer out. Not a chat; no clarifying questions.
- **Opinionated:** if the program isn't stated, infer it or state the assumption at the top of the answer.

## Conflicts between documents
Apply a fixed precedence rule and say which rule decided it:
1. Match the program the question is about.
2. State over federal when both apply.
3. Binding policy over advisory guidance for coverage questions; guidelines win for clinical questions.
4. More recent over older.

Mention the other document in one line.

## Audience
- Users are pharmacists and technicians: use pharmacy acronyms freely, no basic explanations.

## Answer shape
- Readable in about 15 seconds (roughly 60–120 words).
- Numbered steps for processes; a small table for coverage.
- Citations with page links.

## Performance and cost
- End-to-end latency under 30 seconds.
- Cost is not a constraint.

## Evaluation
- Golden set: 20 hand-written questions, plus 3–5 open-ended questions held out for unscripted testing.

## Examples
- `EXAMPLES.md`: 6 question/answer pairs covering multi-document, synthesis, structured data, silence vs
  absence, and conflict, plus at least one real failure (chosen from eval results, not staged) with an
  explanation of why it fails and how it would be fixed.

## Later, once the product works
- AWS deployment
- LangSmith tracing
- Titan embeddings
- A CI feedback loop
