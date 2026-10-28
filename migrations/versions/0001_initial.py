"""Initial schema: patients and calls.

Revision ID: 0001
Revises:
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SEX_VALUES = ("Male", "Female", "Other", "Decline to Answer")


def upgrade() -> None:
    op.create_table(
        "patients",
        sa.Column("patient_id", sa.Uuid(), primary_key=True),
        sa.Column("first_name", sa.String(50), nullable=False),
        sa.Column("last_name", sa.String(50), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("sex", sa.Enum(*SEX_VALUES, name="sex"), nullable=False),
        sa.Column("phone_number", sa.String(10), nullable=False),
        sa.Column("email", sa.String(254)),
        sa.Column("address_line_1", sa.String(100), nullable=False),
        sa.Column("address_line_2", sa.String(100)),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("state", sa.String(2), nullable=False),
        sa.Column("zip_code", sa.String(10), nullable=False),
        sa.Column("insurance_provider", sa.String(100)),
        sa.Column("insurance_member_id", sa.String(30)),
        sa.Column("preferred_language", sa.String(50)),
        sa.Column("emergency_contact_name", sa.String(100)),
        sa.Column("emergency_contact_phone", sa.String(10)),
        sa.Column("source_call_id", sa.String(100), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("length(first_name) BETWEEN 1 AND 50", name="ck_patients_first_name_len"),
        sa.CheckConstraint("length(last_name) BETWEEN 1 AND 50", name="ck_patients_last_name_len"),
        sa.CheckConstraint("length(phone_number) = 10", name="ck_patients_phone_len"),
        sa.CheckConstraint("emergency_contact_phone IS NULL OR length(emergency_contact_phone) = 10",
                           name="ck_patients_ec_phone_len"),
        sa.CheckConstraint("length(city) BETWEEN 1 AND 100", name="ck_patients_city_len"),
        sa.CheckConstraint("length(state) = 2", name="ck_patients_state_len"),
        sa.CheckConstraint("length(zip_code) IN (5, 10)", name="ck_patients_zip_len"),
        sa.CheckConstraint("date_of_birth >= '1900-01-01'", name="ck_patients_dob_min"),
    )
    op.create_index("ix_patients_last_name", "patients", ["last_name"])
    op.create_index("ix_patients_phone_number", "patients", ["phone_number"])
    op.create_index("ix_patients_date_of_birth", "patients", ["date_of_birth"])

    if op.get_bind().dialect.name == "postgresql":
        # Stricter format checks where the database supports regular expressions.
        op.execute("ALTER TABLE patients ADD CONSTRAINT ck_patients_phone_digits CHECK (phone_number ~ '^[2-9][0-9]{2}[2-9][0-9]{6}$')")
        op.execute("ALTER TABLE patients ADD CONSTRAINT ck_patients_ec_phone_digits CHECK (emergency_contact_phone IS NULL OR emergency_contact_phone ~ '^[2-9][0-9]{2}[2-9][0-9]{6}$')")
        op.execute("ALTER TABLE patients ADD CONSTRAINT ck_patients_zip_format CHECK (zip_code ~ '^[0-9]{5}(-[0-9]{4})?$')")
        op.execute("ALTER TABLE patients ADD CONSTRAINT ck_patients_state_upper CHECK (state ~ '^[A-Z]{2}$')")
        op.execute("ALTER TABLE patients ADD CONSTRAINT ck_patients_member_id CHECK (insurance_member_id IS NULL OR insurance_member_id ~ '^[A-Z0-9]{3,30}$')")

    op.create_table(
        "calls",
        sa.Column("call_id", sa.String(100), primary_key=True),
        sa.Column("domain", sa.String(50)),
        sa.Column("caller_number", sa.String(30)),
        sa.Column("record_id", sa.String(64)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("final_payload", sa.JSON()),
        sa.Column("transcript", sa.Text()),
        sa.Column("summary", sa.Text()),
        sa.Column("ended_reason", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_calls_record_id", "calls", ["record_id"])


def downgrade() -> None:
    op.drop_index("ix_calls_record_id", table_name="calls")
    op.drop_table("calls")
    op.drop_index("ix_patients_date_of_birth", table_name="patients")
    op.drop_index("ix_patients_phone_number", table_name="patients")
    op.drop_index("ix_patients_last_name", table_name="patients")
    op.drop_table("patients")
    sa.Enum(name="sex").drop(op.get_bind(), checkfirst=True)
