"""Single, conservative application-side text budget for the Brain UI facade.

MAX_PROMPT_CHARS is measured as Python Unicode string length (characters),
NOT tokens, model context length, or a verified ClickUp product maximum.

The researcher's visible UI accepted a pasted ~40k-character draft (2026-10-28).
Pasting alone does not prove submit, upstream processing, or complete reply
delivery. 50k is an EXPERIMENTAL local guardrail above that observation.
Keep this bounded, fail closed if larger and never silently truncate text.
"""

MAX_PROMPT_CHARS = 50_000
