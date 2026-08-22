"""Prompt Studio CRUD — tune agent prompts without redeploying."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AuthDep, PaginationDep, SessionDep
from app.repositories.content import PromptRepository
from app.schemas.common import APIResponse, MessageResponse, PageMeta
from app.schemas.prompt import PromptTemplateCreate, PromptTemplateRead, PromptTemplateUpdate

router = APIRouter(prefix="/prompts", tags=["prompts"])

#: Agents that can be overridden — mirrors `BaseAgent.name` values.
KNOWN_AGENTS = ["strategist", "copywriter", "visual", "editor", "onboarding", "feedback"]


@router.get("/agents", response_model=APIResponse[list[str]])
async def list_agents(_: AuthDep) -> APIResponse[list[str]]:
    return APIResponse.ok(KNOWN_AGENTS)


@router.get("/defaults/{agent}", response_model=APIResponse[dict])
async def get_default_prompt(agent: str, _: AuthDep) -> APIResponse[dict]:
    """Expose the built-in prompt so the studio can start from it."""
    from app.agents import prompts as prompt_lib

    mapping = {
        "strategist": prompt_lib.STRATEGIST_SYSTEM,
        "copywriter": prompt_lib.COPYWRITER_SYSTEM,
        "visual": prompt_lib.VISUAL_SYSTEM,
        "editor": prompt_lib.EDITOR_SYSTEM,
        "onboarding": prompt_lib.ONBOARDING_SYSTEM,
        "feedback": prompt_lib.VOICE_INSTRUCTION_SYSTEM,
    }
    return APIResponse.ok({"agent": agent, "system_prompt": mapping.get(agent, "")})


@router.get("", response_model=APIResponse[list[PromptTemplateRead]])
async def list_prompts(
    session: SessionDep,
    _: AuthDep,
    page: PaginationDep,
    business_id: Annotated[uuid.UUID | None, Query()] = None,
    agent: Annotated[str | None, Query()] = None,
) -> APIResponse[list[PromptTemplateRead]]:
    rows, total = await PromptRepository(session).search(
        business_id=business_id, agent=agent, offset=page.offset, limit=page.limit
    )
    return APIResponse.ok(
        [PromptTemplateRead.model_validate(row) for row in rows],
        meta=PageMeta(total=total, page=page.page, limit=page.limit),
    )


@router.post("", response_model=APIResponse[PromptTemplateRead], status_code=status.HTTP_201_CREATED)
async def create_prompt(
    payload: PromptTemplateCreate, session: SessionDep, _: AuthDep
) -> APIResponse[PromptTemplateRead]:
    template = await PromptRepository(session).create(**payload.model_dump())
    return APIResponse.ok(PromptTemplateRead.model_validate(template))


@router.get("/{prompt_id}", response_model=APIResponse[PromptTemplateRead])
async def get_prompt(
    prompt_id: uuid.UUID, session: SessionDep, _: AuthDep
) -> APIResponse[PromptTemplateRead]:
    template = await PromptRepository(session).get_or_404(prompt_id)
    return APIResponse.ok(PromptTemplateRead.model_validate(template))


@router.patch("/{prompt_id}", response_model=APIResponse[PromptTemplateRead])
async def update_prompt(
    prompt_id: uuid.UUID, payload: PromptTemplateUpdate, session: SessionDep, _: AuthDep
) -> APIResponse[PromptTemplateRead]:
    repo = PromptRepository(session)
    template = await repo.get_or_404(prompt_id)
    values = payload.model_dump(exclude_unset=True)
    if values.get("system_prompt") and values["system_prompt"] != template.system_prompt:
        template.push_version()          # snapshot before overwriting
    await repo.update(template, values)
    return APIResponse.ok(PromptTemplateRead.model_validate(template))


@router.post("/{prompt_id}/rollback/{version}", response_model=APIResponse[PromptTemplateRead])
async def rollback_prompt(
    prompt_id: uuid.UUID, version: int, session: SessionDep, _: AuthDep
) -> APIResponse[PromptTemplateRead]:
    from app.core.exceptions import NotFoundError

    repo = PromptRepository(session)
    template = await repo.get_or_404(prompt_id)
    snapshot = next((v for v in template.versions if int(v.get("version", -1)) == version), None)
    if snapshot is None:
        raise NotFoundError(f"Version {version} not found")

    template.push_version()
    template.system_prompt = str(snapshot["system_prompt"])
    await session.flush()
    return APIResponse.ok(PromptTemplateRead.model_validate(template))


@router.delete("/{prompt_id}", response_model=APIResponse[MessageResponse])
async def delete_prompt(
    prompt_id: uuid.UUID, session: SessionDep, _: AuthDep
) -> APIResponse[MessageResponse]:
    repo = PromptRepository(session)
    await repo.delete(await repo.get_or_404(prompt_id))
    return APIResponse.ok(MessageResponse(message="Prompt deleted"))
