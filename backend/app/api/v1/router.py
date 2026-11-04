"""Aggregate router for API version 1."""

from fastapi import APIRouter

from app.api.v1 import auth, integrations, jobs, profile, resumes

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(profile.router)
api_router.include_router(resumes.router)
api_router.include_router(integrations.router)
api_router.include_router(jobs.router)
