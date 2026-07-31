"""Migration parsing and shared SQL table extraction."""

from adduce.parsers.migration_parser import (
    MigrationInfo, is_migration_file, parse_migration, parse_sql_tables,
)

FLYWAY_V2 = """\
-- Add owners and link visits to them.
CREATE TABLE IF NOT EXISTS owners (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    first_name VARCHAR(30),
    city VARCHAR(80)
) engine=InnoDB;

ALTER TABLE visits ADD COLUMN owner_id INT NOT NULL;
CREATE INDEX idx_owners_last_name ON owners (last_name);
DROP TABLE legacy_owner_audit;
"""

ALEMBIC_REV = """\
\"\"\"add owners

Revision ID: 3f2a1bc9d0e1
Revises: 91c0ffee0000
\"\"\"
from alembic import op
import sqlalchemy as sa

revision = '3f2a1bc9d0e1'
down_revision = '91c0ffee0000'


def upgrade():
    op.create_table(
        'owners',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('city', sa.String(80)),
    )
    op.add_column('visits', sa.Column('owner_id', sa.Integer()))
    op.drop_table('legacy_owner_audit')


def downgrade():
    op.drop_table('owners')
    op.drop_column('visits', 'owner_id')
"""

DJANGO_MIG = """\
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('clinic', '0001_initial')]

    operations = [
        migrations.CreateModel(
            name='Owner',
            fields=[('id', models.AutoField(primary_key=True))],
            options={'db_table': 'clinic_owners'},
        ),
        migrations.CreateModel(
            name='Visit',
            fields=[('id', models.AutoField(primary_key=True))],
        ),
        migrations.AddField(model_name='pet', name='owner', field=models.ForeignKey('Owner', on_delete=models.CASCADE)),
        migrations.DeleteModel(name='LegacyAudit'),
    ]
"""

LIQUIBASE_XML = """\
<databaseChangeLog xmlns="http://www.liquibase.org/xml/ns/dbchangelog">
  <changeSet id="2024-03-owners" author="pols">
    <createTable tableName="owners">
      <column name="id" type="int"/>
    </createTable>
    <addColumn tableName="visits">
      <column name="owner_id" type="int"/>
    </addColumn>
    <dropTable tableName="legacy_owner_audit"/>
    <sql>ALTER TABLE pets ADD COLUMN owner_id INT;</sql>
  </changeSet>
</databaseChangeLog>
"""

RAILS_MIG = """\
class CreateOwners < ActiveRecord::Migration[7.0]
  def change
    create_table :owners do |t|
      t.string :first_name
      t.timestamps
    end
    add_column :visits, :owner_id, :integer
    drop_table :legacy_owner_audit
  end
end
"""

EF_MIG = """\
using Microsoft.EntityFrameworkCore.Migrations;

namespace PetClinic.Migrations
{
    [Migration("20240301120000_AddOwners")]
    public partial class AddOwners : Migration
    {
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "Owners",
                columns: table => new { Id = table.Column<int>(nullable: false) });
            migrationBuilder.AddColumn<int>(
                name: "OwnerId",
                table: "Visits",
                nullable: false);
            migrationBuilder.DropTable(name: "LegacyOwnerAudit");
        }
    }
}
"""


class TestFlyway:
    def test_path_and_versioned_name_detection(self):
        assert is_migration_file("src/main/resources/db/migration/V2__add_owners.sql")
        assert is_migration_file("V1_2__seed_data.sql")
        assert not is_migration_file("src/main/java/OwnerController.java")
        assert not is_migration_file("docs/queries.sql")  # parsed, but not a migration

    def test_create_alter_drop_and_version(self):
        info = parse_migration("db/migration/V2__add_owners.sql", FLYWAY_V2)
        assert info.framework == "flyway"
        assert info.version == "V2"
        assert info.tables_created == ["owners"]
        assert info.tables_altered == ["visits"]
        assert info.tables_dropped == ["legacy_owner_audit"]


class TestAlembic:
    def test_versions_tree_detection(self):
        assert is_migration_file("alembic/versions/3f2a1bc9d0e1_add_owners.py")
        assert not is_migration_file("app/models/owner.py")

    def test_revision_and_upgrade_only(self):
        info = parse_migration("migrations/versions/3f2a_add_owners.py", ALEMBIC_REV)
        assert info.framework == "alembic"
        assert info.version == "3f2a1bc9d0e1"
        assert info.tables_created == ["owners"]
        assert info.tables_altered == ["visits"]
        # downgrade()'s drop_table('owners') must not be reported
        assert info.tables_dropped == ["legacy_owner_audit"]


class TestDjango:
    def test_db_table_wins_model_name_falls_back(self):
        info = parse_migration("clinic/migrations/0002_add_owner.py", DJANGO_MIG)
        assert info.framework == "django"
        assert info.version == "0002"
        assert info.tables_created == ["clinic_owners", "visit"]
        assert info.tables_altered == ["pet"]
        assert info.tables_dropped == ["legacyaudit"]


class TestLiquibase:
    def test_xml_changesets_and_raw_sql_block(self):
        info = parse_migration("db/changelog/db.changelog-owners.xml", LIQUIBASE_XML)
        assert info.framework == "liquibase"
        assert info.version == "2024-03-owners"
        assert info.tables_created == ["owners"]
        assert set(info.tables_altered) == {"visits", "pets"}  # pets via <sql>
        assert info.tables_dropped == ["legacy_owner_audit"]

    def test_yaml_changelog(self):
        yaml = (
            "databaseChangeLog:\n"
            "  - changeSet:\n"
            "      id: owners-1\n"
            "      changes:\n"
            "        - createTable:\n"
            "            tableName: owners\n"
        )
        info = parse_migration("db/changelog/changelog-master.yaml", yaml)
        assert info.tables_created == ["owners"]
        assert info.version == "owners-1"


class TestRails:
    def test_create_add_column_drop(self):
        info = parse_migration("db/migrate/20240301120000_create_owners.rb", RAILS_MIG)
        assert info.framework == "rails"
        assert info.version == "20240301120000"
        assert info.tables_created == ["owners"]
        assert info.tables_altered == ["visits"]
        assert info.tables_dropped == ["legacy_owner_audit"]


class TestPrismaAndEf:
    def test_prisma_migration_sql(self):
        sql = 'CREATE TABLE "owners" (id SERIAL PRIMARY KEY);'
        info = parse_migration(
            "prisma/migrations/20240301120000_add_owners/migration.sql", sql)
        assert info.framework == "prisma"
        assert info.version == "20240301120000_add_owners"
        assert info.tables_created == ["owners"]

    def test_ef_migration_builder(self):
        info = parse_migration("Migrations/20240301120000_AddOwners.cs", EF_MIG)
        assert info.framework == "ef"
        assert info.version == "20240301120000_AddOwners"
        assert info.tables_created == ["owners"]
        assert info.tables_altered == ["visits"]
        assert info.tables_dropped == ["legacyowneraudit"]


class TestStandaloneSql:
    def test_sql_outside_migration_tree_still_parses(self):
        info = parse_migration("scripts/report.sql",
                               "SELECT o.name FROM owners o JOIN visits v ON v.owner_id = o.id;")
        assert info.framework == "sql"
        assert info.version == ""
        assert info.tables_created == []

    def test_non_sql_non_migration_returns_none(self):
        assert parse_migration("src/app/service.py", "print('hi')") is None


class TestParseSqlTables:
    def test_reads_writes_and_schema_qualified(self):
        out = parse_sql_tables(
            "SELECT * FROM public.owners o JOIN visits v ON v.owner_id = o.id;\n"
            "INSERT INTO audit_log (msg) VALUES ('x');\n"
            "UPDATE owners SET city = 'SF' WHERE id = 1;\n"
            "DELETE FROM sessions WHERE expired;")
        assert [n for n, _, _ in out["reads"]] == ["public.owners", "visits"]
        assert [n for n, _, _ in out["writes"]] == ["audit_log", "owners", "sessions"]

    def test_delete_from_not_double_counted_as_read(self):
        out = parse_sql_tables("DELETE FROM sessions")
        assert out["reads"] == []

    def test_subquery_and_quotes_and_case(self):
        out = parse_sql_tables('SELECT * FROM (SELECT 1) t; SELECT id FROM "Owners"')
        assert [n for n, _, _ in out["reads"]] == ["owners"]
        assert out["reads"][0][2] == '"Owners"'   # raw spelling preserved

    def test_procedures_and_dynamic_placeholders(self):
        out = parse_sql_tables("CALL refresh_owner_stats(1); EXEC dbo.sp_prune")
        assert [n for n, _, _ in out["procedures"]] == ["refresh_owner_stats", "dbo.sp_prune"]
        dyn = parse_sql_tables("SELECT * FROM {table}; INSERT INTO %s VALUES (1)")
        assert dyn["reads"] == []
        assert dyn["dynamic"] == [("reads", 1), ("writes", 1)]

    def test_update_without_set_is_not_a_table(self):
        assert parse_sql_tables("-- update owners frequently")["writes"] == []


class TestMalformed:
    def test_garbage_inputs_do_not_raise(self):
        assert isinstance(parse_migration("db/migration/V9__x.sql", "\x00\xff garbage ((("),
                          MigrationInfo)
        assert parse_migration("db/migrate/20240101_x.rb", "") == MigrationInfo(
            framework="rails", version="20240101")
        assert parse_migration("db/changelog/changelog.xml", "<not-closed") is not None
        assert parse_migration("", "SELECT 1") is None
