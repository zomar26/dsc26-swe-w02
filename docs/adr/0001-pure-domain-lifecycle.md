# 0001. Pure Domain Lifecycle Module

## Status
Accepted

## Context
Tawseel's parcel lifecycle rules (dispatch, fail, retry, and return) are actively evolving as business rules change. Coupling state machine transitions directly to web frameworks (such as FastAPI, Starlette, or Pydantic) or database ORMs makes testing cumbersome and creates high friction when adapting business invariants.

## Decision
We isolate parcel state transitions inside a standalone, pure Python module (`app/domain.py`) with zero framework dependencies. All parcel records are represented by immutable frozen dataclasses, and state modifications occur strictly via a pure `apply_event` function returning new instances or raising an `InvalidTransition` exception.

## Consequences
- Business logic is completely decoupled from HTTP protocols and database schemas.
- Exhaustive transition testing can execute with property-based testing suites like Hypothesis at high speed without mocks or database harnesses.
- The web API layer acts strictly as an adapter translating HTTP requests to domain events.