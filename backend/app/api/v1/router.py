"""Aggregate router for API version 1."""

from fastapi import APIRouter

from app.api.v1 import auth

api_router = APIRouter()
api_router.include_router(auth.router)
