# 0002. Cursor-Based Pagination for Parcels

## Status
Accepted

## Context
Couriers and merchants frequently query parcels filtered by active operational states (such as `state=created`). When couriers accept and dispatch parcels, earlier records transition to `out_for_delivery`. In traditional limit/offset pagination, this shift causes the window to slide forward, skipping unvisited records on subsequent pages.

## Decision
We implement opaque, sequential cursor-based pagination. Cursors represent an opaque pointer into the immutable parcel insertion sequence rather than a filtered set offset. The server resumes iterating from the exact insertion index of the previous page.

## Consequences
- Clients filtering on dynamic states will not miss parcels or encounter duplicates when earlier parcels change state mid-walk.
- The pagination contract avoids exposing internal database primary keys or direct numerical offsets to external consumers.
- Query clients must iterate sequentially and cannot jump arbitrarily to page $N$.