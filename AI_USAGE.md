# AI Usage Record

## Tools
- Claude 3.5 Sonnet / Gemini (via IDE completion and code review assistance)

## What AI got wrong
- Initial generated drafts attempted to implement offset-based pagination directly within the filtered collection, which causes parcels to shift and skip when an item on page 1 changes state between successive page fetches.
- FastAPI's default 422 exception handler formats errors into an unstandardized dictionary format instead of the mandated RFC 9457 `application/problem+json` format with explicit `loc` and `msg` properties.

## In my own words
Offset pagination fails when items change state during a pagination walk because removing earlier items shifts subsequent items into earlier index positions, skipping records.

Renaming any field in `getParcel` or `recordParcelEvent` would break the courier app, and that change would require formal approval from the mobile tech lead and the dispatch backend lead.