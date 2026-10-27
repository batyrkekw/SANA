import argparse
import json
import uuid

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.db import session_factory
from app.models import Plan, Profile, Subscription, TokenTransaction
from app.services import lock_account, user_plan


class Limits(BaseModel):
    max_tokens: int = Field(ge=1, le=1000000)
    kinds: list[str]
    images: bool
    max_prompt: int = Field(ge=1, le=6000)
    max_length: int = Field(ge=1, le=12)
    max_panels: int = Field(ge=0, le=8)
    max_images: int = Field(ge=0, le=8)


class PlanConfig(BaseModel):
    code: str = Field(pattern="^(basic|pro|plus)$")
    name: dict[str, str]
    initial_tokens: int = Field(ge=0, le=1000000)
    limits: Limits

    @model_validator(mode="after")
    def grant_within_limit(self):
        if self.initial_tokens > self.limits.max_tokens:
            raise ValueError("Initial tokens cannot exceed the plan's maximum balance")
        return self


def seed_plans(db, path=None):
    definitions = json.loads((path or get_settings().plan_config_path).read_text())
    for definition in definitions:
        value = PlanConfig.model_validate(definition).model_dump()
        statement = insert(Plan).values(**value)
        db.execute(statement.on_conflict_do_update(index_elements=["code"], set_=value))


def main():
    parser = argparse.ArgumentParser(
        description="SANA administrator commands (no public admin API)"
    )
    parser.add_argument(
        "command", choices=["seed-plans", "assign-plan", "grant", "reconcile", "prepare-model"]
    )
    parser.add_argument("--supabase-id", type=uuid.UUID)
    parser.add_argument("--plan", choices=["basic", "pro", "plus"])
    parser.add_argument("--amount", type=int)
    parser.add_argument("--operation-id", type=uuid.UUID)
    args = parser.parse_args()
    if args.command == "prepare-model":
        from huggingface_hub import snapshot_download

        config = get_settings()
        variant = f".{config.image_variant}" if config.image_variant else ""
        snapshot_download(
            config.image_model_id,
            cache_dir=config.model_cache_dir,
            allow_patterns=[
                "model_index.json",
                "*/config.json",
                "scheduler/*.json",
                "tokenizer/*",
                "tokenizer_2/*",
                "feature_extractor/*.json",
                f"unet/diffusion_pytorch_model{variant}.safetensors",
                f"vae/diffusion_pytorch_model{variant}.safetensors",
                f"text_encoder/model{variant}.safetensors",
                f"text_encoder_2/model{variant}.safetensors",
                f"safety_checker/model{variant}.safetensors",
            ],
        )
        print("Model downloaded. Run the documented inference smoke check to verify it.")
        return
    with session_factory().begin() as db:
        if args.command == "seed-plans":
            seed_plans(db)
            print("Plan definitions updated. Existing balances unchanged.")
            return
        if not args.supabase_id:
            parser.error("--supabase-id is required")
        profile = db.scalar(select(Profile).where(Profile.supabase_id == args.supabase_id))
        if not profile:
            parser.error("Profile not found; sign in once first")
        account = lock_account(db, profile.id)
        if args.command == "assign-plan":
            if not args.plan or not db.get(Plan, args.plan):
                parser.error("A seeded --plan is required")
            if account.available + account.reserved > db.get(Plan, args.plan).limits["max_tokens"]:
                parser.error("Balance exceeds the target plan limit; no tokens were removed")
            db.get(Subscription, profile.id).plan_code = args.plan
            print("Plan changed. Balance unchanged; use an explicit grant if needed.")
        elif args.command == "grant":
            if not args.amount or args.amount <= 0 or not args.operation_id:
                parser.error("Positive --amount and unique --operation-id are required")
            key = f"admin:{args.operation_id}"
            prior = db.scalar(select(TokenTransaction).where(TokenTransaction.operation_key == key))
            if prior:
                if prior.owner_id != profile.id or prior.amount != args.amount:
                    parser.error("Operation id already belongs to a different adjustment")
                print("Already applied.")
                return
            if (
                account.available + account.reserved + args.amount
                > user_plan(db, profile.id).limits["max_tokens"]
            ):
                parser.error("Grant would exceed the plan's maximum balance")
            account.available += args.amount
            db.add(
                TokenTransaction(
                    owner_id=profile.id,
                    kind="adjustment",
                    amount=args.amount,
                    available_delta=args.amount,
                    reserved_delta=0,
                    operation_key=key,
                    reason="administrator_grant",
                )
            )
            print("Grant applied.")
        elif args.command == "reconcile":
            entries = db.scalars(
                select(TokenTransaction).where(TokenTransaction.owner_id == profile.id)
            ).all()
            expected = (
                sum(e.available_delta for e in entries),
                sum(e.reserved_delta for e in entries),
            )
            actual = (account.available, account.reserved)
            if actual != expected:
                raise SystemExit("Ledger mismatch; no data changed")
            print("Ledger matches account.")


if __name__ == "__main__":
    main()
