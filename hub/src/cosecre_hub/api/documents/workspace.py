"""Settings for the documents app: which spreadsheet, which tabs, which model."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ...deps import get_current_user, get_db, get_workspace_setting, require_admin
from ...models import User, WorkspaceSetting
from ...schemas import WorkspaceSettingsRead, WorkspaceSettingsUpdate
from ...services.sheets import parse_spreadsheet_id

router = APIRouter()


def _read(request: Request, workspace: WorkspaceSetting) -> WorkspaceSettingsRead:
    return WorkspaceSettingsRead(
        spreadsheet_url=workspace.spreadsheet_url,
        registry_sheet_name=workspace.registry_sheet_name,
        sheet_name=workspace.sheet_name,
        ticket_sheet_name=workspace.ticket_sheet_name,
        openai_model=workspace.openai_model,
        extraction_prompt=workspace.extraction_prompt,
        polling_interval_seconds=workspace.polling_interval_seconds,
        classifier_configured=request.app.state.classifier.configured,
        drive_folder_configured=request.app.state.settings.documents_folder_id is not None,
    )


@router.get("", response_model=WorkspaceSettingsRead)
def read_settings(
    request: Request, session: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    """Readable by any signed-in user.

    Clients use ``polling_interval_seconds`` to pace themselves, so gating this
    behind admin would leave ordinary users guessing.
    """
    return _read(request, get_workspace_setting(session))


@router.put("", response_model=WorkspaceSettingsRead)
def update_settings(
    request: Request,
    payload: WorkspaceSettingsUpdate,
    session: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    workspace = get_workspace_setting(session)
    spreadsheet_id = None
    if payload.spreadsheet_url:
        try:
            spreadsheet_id = parse_spreadsheet_id(payload.spreadsheet_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    workspace.spreadsheet_url = payload.spreadsheet_url
    workspace.spreadsheet_id = spreadsheet_id
    workspace.registry_sheet_name = payload.registry_sheet_name
    workspace.sheet_name = payload.sheet_name
    workspace.ticket_sheet_name = payload.ticket_sheet_name
    workspace.openai_model = payload.openai_model
    workspace.extraction_prompt = payload.extraction_prompt
    workspace.polling_interval_seconds = payload.polling_interval_seconds
    workspace.updated_by_id = admin.id
    session.add(workspace)
    session.commit()
    session.refresh(workspace)
    request.app.state.register_synced_at = 0.0  # a new sheet or tab: sync on the next read
    return _read(request, workspace)
