from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.core.auth import AuthUser, require_operator, require_viewer
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models import AuditLog, BomDocument
from app.schemas import BomDocumentOut
from app.services.bom import BomAnalyzer

router = APIRouter(
    prefix="/api/bom",
    tags=["bom"],
    dependencies=[Depends(require_viewer)],
)


@router.post("/analyze", response_model=BomDocumentOut)
def analyze_bom(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: AuthUser = Depends(require_operator),
) -> BomDocument:
    try:
        document = BomAnalyzer(db, settings).analyze_upload(
            filename=file.filename or "upload",
            content_type=file.content_type,
            file=file.file,
        )
        db.add(
            AuditLog(
                actor=user.email,
                action="bom.analyzed",
                target=document.id,
                detail={"filename": file.filename or "upload"},
            )
        )
        db.commit()
        return document
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[BomDocumentOut])
def list_documents(db: Session = Depends(get_db)) -> list[BomDocument]:
    return list(
        db.scalars(
            select(BomDocument)
            .options(selectinload(BomDocument.items), selectinload(BomDocument.recommendations))
            .order_by(desc(BomDocument.created_at))
            .limit(25)
        )
    )


@router.get("/{document_id}", response_model=BomDocumentOut)
def get_document(document_id: str, db: Session = Depends(get_db)) -> BomDocument:
    document = db.scalar(
        select(BomDocument)
        .where(BomDocument.id == document_id)
        .options(selectinload(BomDocument.items), selectinload(BomDocument.recommendations))
    )
    if not document:
        raise HTTPException(status_code=404, detail="BOM document not found")
    return document
