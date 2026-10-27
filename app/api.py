import base64
import json
import uuid
from typing import Annotated, Any

from fastapi import FastAPI, Header, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.domain import EventType, InvalidTransition, Parcel, ParcelState, apply_event

PROBLEM_MEDIA_TYPE = "application/problem+json"


def problem_response(
    status_code: int,
    title: str,
    detail: str | None = None,
    errors: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    content: dict[str, Any] = {
        "type": f"https://httpstatuses.com/{status_code}",
        "title": title,
        "status": status_code,
    }
    if detail:
        content["detail"] = detail
    if errors is not None:
        content["errors"] = errors
    return JSONResponse(
        status_code=status_code,
        content=content,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


class CreateParcelRequest(BaseModel):
    merchant_ref: str = Field(..., min_length=1, max_length=64)
    cod_amount_piastres: int = Field(..., ge=0, le=5_000_000)
    address_text: str = Field(..., min_length=1, max_length=500)


class ParcelResponse(BaseModel):
    id: str
    merchant_ref: str
    cod_amount_piastres: int
    address_text: str
    state: ParcelState
    attempts: int


class ListParcelsResponse(BaseModel):
    items: list[ParcelResponse]
    next_cursor: str | None


class RecordEventRequest(BaseModel):
    type: EventType


class ProblemDetail(BaseModel):
    type: str
    title: str
    status: int
    detail: str | None = None
    errors: list[dict[str, Any]] | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="Tawseel Dispatch API")

    # Instance-isolated in-memory storage
    parcels_by_id: dict[str, Parcel] = {}
    parcels_list: list[str] = []  # Keeps creation order of IDs
    merchant_refs: set[str] = set()

    # Cursor validation & encoding: opaque token anchored to insertion index
    def encode_cursor(index: int) -> str:
        payload = json.dumps({"idx": index, "salt": "dsc26"})
        return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")

    def decode_cursor(token: str) -> int:
        try:
            raw = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
            data = json.loads(raw)
            if data.get("salt") != "dsc26" or not isinstance(data.get("idx"), int):
                raise ValueError
            return data["idx"]
        except Exception:
            raise ValueError("Malformed or untrusted cursor")

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        raw_errors = exc.errors()
        parsed_errors = [
            {"loc": list(err["loc"]), "msg": err["msg"]} for err in raw_errors
        ]
        return problem_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Unprocessable Entity",
            errors=parsed_errors,
        )

    @app.post(
        "/v1/parcels",
        operation_id="createParcel",
        status_code=status.HTTP_201_CREATED,
        response_model=ParcelResponse,
        responses={
            409: {"model": ProblemDetail, "description": "Duplicate merchant_ref"},
            422: {"model": ProblemDetail, "description": "Validation error"},
        },
    )
    def create_parcel(req: CreateParcelRequest):
        if req.merchant_ref in merchant_refs:
            return problem_response(
                status_code=status.HTTP_409_CONFLICT,
                title="Conflict",
                detail=f"merchant_ref '{req.merchant_ref}' already exists",
            )

        parcel_id = f"pcl_{uuid.uuid4().hex[:12]}"
        new_parcel = Parcel(
            id=parcel_id,
            merchant_ref=req.merchant_ref,
            cod_amount_piastres=req.cod_amount_piastres,
            address_text=req.address_text,
        )

        merchant_refs.add(req.merchant_ref)
        parcels_by_id[parcel_id] = new_parcel
        parcels_list.append(parcel_id)

        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "id": new_parcel.id,
                "merchant_ref": new_parcel.merchant_ref,
                "cod_amount_piastres": new_parcel.cod_amount_piastres,
                "address_text": new_parcel.address_text,
                "state": new_parcel.state.value,
                "attempts": new_parcel.attempts,
            },
            headers={"Location": f"/v1/parcels/{parcel_id}"},
        )

    @app.get(
        "/v1/parcels/{parcel_id}",
        operation_id="getParcel",
        response_model=ParcelResponse,
        responses={
            404: {"model": ProblemDetail, "description": "Parcel not found"}
        },
    )
    def get_parcel(parcel_id: str):
        parcel = parcels_by_id.get(parcel_id)
        if not parcel:
            return problem_response(
                status_code=status.HTTP_404_NOT_FOUND,
                title="Not Found",
                detail=f"Parcel {parcel_id} not found",
            )
        return {
            "id": parcel.id,
            "merchant_ref": parcel.merchant_ref,
            "cod_amount_piastres": parcel.cod_amount_piastres,
            "address_text": parcel.address_text,
            "state": parcel.state.value,
            "attempts": parcel.attempts,
        }

    @app.get(
        "/v1/parcels",
        operation_id="listParcels",
        response_model=ListParcelsResponse,
        responses={
            400: {"model": ProblemDetail, "description": "Bad cursor"},
            422: {"model": ProblemDetail, "description": "Bad state or limit"},
        },
    )
    def list_parcels(
        state: ParcelState | None = Query(None),
        limit: int = Query(20, ge=1, le=100),
        cursor: str | None = Query(None),
    ):
        start_idx = 0
        if cursor is not None:
            try:
                start_idx = decode_cursor(cursor)
                if start_idx < 0 or start_idx > len(parcels_list):
                    raise ValueError
            except ValueError:
                return problem_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    title="Bad Request",
                    detail="Invalid cursor token",
                )

        matched_items: list[dict[str, Any]] = []
        next_cursor: str | None = None
        current_idx = start_idx
        total_parcels = len(parcels_list)

        while current_idx < total_parcels and len(matched_items) < limit:
            p_id = parcels_list[current_idx]
            parcel = parcels_by_id[p_id]
            if state is None or parcel.state == state:
                matched_items.append(
                    {
                        "id": parcel.id,
                        "merchant_ref": parcel.merchant_ref,
                        "cod_amount_piastres": parcel.cod_amount_piastres,
                        "address_text": parcel.address_text,
                        "state": parcel.state.value,
                        "attempts": parcel.attempts,
                    }
                )
            current_idx += 1

        # Check if there are any remaining matching items beyond current_idx
        has_more = False
        scan_idx = current_idx
        while scan_idx < total_parcels:
            scan_id = parcels_list[scan_idx]
            scan_p = parcels_by_id[scan_id]
            if state is None or scan_p.state == state:
                has_more = True
                break
            scan_idx += 1

        if has_more:
            next_cursor = encode_cursor(current_idx)

        return {"items": matched_items, "next_cursor": next_cursor}

    @app.post(
        "/v1/parcels/{parcel_id}/events",
        operation_id="recordParcelEvent",
        response_model=ParcelResponse,
        responses={
            404: {"model": ProblemDetail, "description": "Parcel not found"},
            409: {"model": ProblemDetail, "description": "Invalid transition"},
            422: {"model": ProblemDetail, "description": "Unknown or missing event type"},
        },
    )
    def record_parcel_event(parcel_id: str, req: RecordEventRequest):
        parcel = parcels_by_id.get(parcel_id)
        if not parcel:
            return problem_response(
                status_code=status.HTTP_404_NOT_FOUND,
                title="Not Found",
                detail=f"Parcel {parcel_id} not found",
            )

        try:
            updated = apply_event(parcel, req.type)
        except InvalidTransition as exc:
            return problem_response(
                status_code=status.HTTP_409_CONFLICT,
                title="Conflict",
                detail=str(exc),
            )

        parcels_by_id[parcel_id] = updated
        return {
            "id": updated.id,
            "merchant_ref": updated.merchant_ref,
            "cod_amount_piastres": updated.cod_amount_piastres,
            "address_text": updated.address_text,
            "state": updated.state.value,
            "attempts": updated.attempts,
        }

    return app


app = create_app()