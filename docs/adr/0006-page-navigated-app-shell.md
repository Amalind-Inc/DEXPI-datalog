# Page-Navigated App Shell Over Flyout Overlays

The app shell moves from a narrow icon-only rail with transient flyout
overlays (Sessions, Rule Packs) to a wider sidebar with icon+label
destinations that navigate the main content area to real, routed pages:
`/assistant`, `/projects`, `/projects/[id]`, `/rule-packs`,
`/rule-packs/[id]`. The chat+P&ID review surface becomes one destination
("Assistant") rather than the app's only surface. The sidebar itself can be
fully hidden on desktop (main content expands, a small toggle reopens it); it
does not permanently collapse to an icon-only mini-rail except as a
narrow-viewport fallback.

This was chosen over restyling the existing rail-plus-flyout pattern because
two new requirements need real page real estate and persistent, linkable
navigation state that an overlay can't hold well: a searchable/browsable rule
pack table (read-only reference, no session required) and a `review project`
grouping multiple chats, each already able to attach several sessions and
rule packs. Flyouts are built for transient, chat-scoped actions (attaching a
pack or a diagram to the active chat), not for browsing or for a nested
project/chat tree that the user expects to navigate back to via the URL or
browser back button.

The trade-off accepted: more routing surface and per-page data loading to
maintain, versus the flyout model's simplicity. The in-context action of
attaching a rule pack (or a diagram) to a chat remains a modal (not a page),
since loading and running a pack is inherently tied to whichever chat is
active — that action stays close to the chat rather than becoming a
standalone page.
